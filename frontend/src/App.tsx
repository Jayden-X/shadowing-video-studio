import { useEffect, useRef, useState } from "react";

import { SentenceSpeech, SpeechControls } from "./SpeechControls";
import { useSpeech } from "./useSpeech";
import { VideoControls } from "./VideoControls";
import { useVideo } from "./useVideo";
import { useVisuals } from "./useVisuals";
import { useVisualSelections } from "./useVisualSelections";
import { BackgroundImageControls, SentenceIllustrationPicker } from "./VisualAssets";

import {
  getBackendHealth,
  getTextProviders,
  prepareText,
  TextApiError,
  type TextProposal,
  type TextProvider,
  type TextProviderId,
} from "./api";
import {
  createSentenceDocument,
  createSentenceDocumentFromProposal,
  deleteSentence,
  insertSentenceAfter,
  mergeWithPrevious,
  moveSentence,
  splitSentence,
  updateSentenceText,
  MAX_SOURCE_LENGTH,
  type SentenceDocument,
  type SentenceId,
} from "./domain/sentences";

type BackendState = "checking" | "online" | "offline";
type PreparationMode = "manual" | "ai";
type Replacement = { kind: "manual"; source: string } | { kind: "ai"; proposal: TextProposal };
const AI_REQUEST_TIMEOUT_MS = 120_000;

export default function App() {
  const speech = useSpeech();
  const video = useVideo();
  const visuals = useVisuals();
  const visualSelectionState = useVisualSelections();
  const { backgroundAssetId, illustrationsBySentence } = visualSelectionState.selections;
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [sourceDraft, setSourceDraft] = useState("");
  const [sentenceDocument, setSentenceDocument] = useState(() => createSentenceDocument(""));
  const [hasPrepared, setHasPrepared] = useState(false);
  const [replacement, setReplacement] = useState<Replacement | null>(null);
  const [notice, setNotice] = useState("");
  const [mode, setMode] = useState<PreparationMode>("manual");
  const [providers, setProviders] = useState<TextProvider[]>([]);
  const [providerStatus, setProviderStatus] = useState<BackendState>("checking");
  const [selectedProvider, setSelectedProvider] = useState<TextProviderId | "">("");
  const [proposal, setProposal] = useState<TextProposal | null>(null);
  const [aiPending, setAiPending] = useState(false);
  const [aiError, setAiError] = useState("");
  const sentenceInputs = useRef(new Map<SentenceId, HTMLTextAreaElement>());
  const prepareButton = useRef<HTMLButtonElement>(null);
  const applyButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  const confirmationOrigin = useRef<PreparationMode>("manual");
  const activeRequest = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);
  const requestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    getBackendHealth()
      .then(() => {
        if (active) setBackendState("online");
      })
      .catch(() => {
        if (active) setBackendState("offline");
      });
    getTextProviders(controller.signal)
      .then((availableProviders) => {
        if (!active) return;
        setProviders(availableProviders);
        setProviderStatus("online");
      })
      .catch(() => {
        if (active) setProviderStatus("offline");
      });
    return () => {
      active = false;
      controller.abort();
      requestSequence.current += 1;
      activeRequest.current?.abort();
      if (requestTimer.current !== null) clearTimeout(requestTimer.current);
    };
  }, []);

  useEffect(() => {
    if (replacement !== null) cancelButton.current?.focus();
    else if (wasConfirming.current) {
      if (confirmationOrigin.current === "ai" && applyButton.current) applyButton.current.focus();
      else prepareButton.current?.focus();
    }
    wasConfirming.current = replacement !== null;
  }, [replacement]);

  function prepareSentences(source: string) {
    const prepared = createSentenceDocument(source);
    setSentenceDocument(prepared);
    visualSelectionState.clearSentenceIllustrations();
    speech.resetSelection();
    video.resetDocument();
    setHasPrepared(true);
    setReplacement(null);
    setNotice(`Prepared ${prepared.sentences.length} sentences. Your source snapshot is saved below.`);
  }

  function requestPreparation() {
    if (hasPrepared || sentenceDocument.sentences.length > 0) {
      confirmationOrigin.current = "manual";
      setReplacement({ kind: "manual", source: sourceDraft });
      return;
    }
    prepareSentences(sourceDraft);
  }

  function stopWaiting(timedOut = false) {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    if (requestTimer.current !== null) clearTimeout(requestTimer.current);
    requestTimer.current = null;
    setAiPending(false);
    if (timedOut) setAiError("AI preparation timed out. Your source and current edits are preserved.");
    else setNotice("Stopped waiting for the AI result. The provider may still be running; your current work is preserved.");
  }

  async function requestAiPreparation() {
    const provider = providers.find((item) => item.id === selectedProvider && item.available);
    if (!provider || aiPending || proposal || !sourceDraft.trim() || sourceDraft.length > MAX_SOURCE_LENGTH) return;
    const controller = new AbortController();
    const sequence = ++requestSequence.current;
    activeRequest.current = controller;
    setAiError("");
    setNotice("");
    setAiPending(true);
    requestTimer.current = setTimeout(() => stopWaiting(true), AI_REQUEST_TIMEOUT_MS);
    try {
      const result = await prepareText(provider.id, sourceDraft, controller.signal);
      if (sequence !== requestSequence.current || controller.signal.aborted) return;
      setProposal(result);
      setNotice("AI proposal ready for review. Your current sentence list has not changed.");
    } catch (error: unknown) {
      if (sequence !== requestSequence.current || controller.signal.aborted) return;
      setAiError(error instanceof TextApiError ? error.message : "AI preparation failed. Your source and current edits are preserved.");
    } finally {
      if (sequence === requestSequence.current) {
        if (requestTimer.current !== null) clearTimeout(requestTimer.current);
        requestTimer.current = null;
        activeRequest.current = null;
        setAiPending(false);
      }
    }
  }

  function applyProposal(reviewed: TextProposal) {
    const accepted = createSentenceDocumentFromProposal(reviewed.sourceText, reviewed.sentences);
    setSentenceDocument(accepted);
    visualSelectionState.clearSentenceIllustrations();
    speech.resetSelection();
    video.resetDocument();
    setHasPrepared(true);
    setProposal(null);
    setReplacement(null);
    setNotice(`Applied ${accepted.sentences.length} reviewed sentences. Use the manual tools to make corrections.`);
  }

  function requestProposalApplication() {
    if (!proposal) return;
    if (hasPrepared || sentenceDocument.sentences.length > 0) {
      confirmationOrigin.current = "ai";
      setReplacement({ kind: "ai", proposal });
      return;
    }
    applyProposal(proposal);
  }

  function applyOperation(operation: (current: SentenceDocument) => SentenceDocument, message: string) {
    setSentenceDocument(operation);
    setNotice(message);
  }

  function splitAtCursor(id: SentenceId, position: number) {
    const input = sentenceInputs.current.get(id);
    if (!input) return;

    if (input.selectionStart !== input.selectionEnd) {
      setNotice("Collapse the selection to a single cursor position before splitting.");
      input.focus();
      return;
    }

    const updated = splitSentence(sentenceDocument, id, input.selectionStart);
    if (updated === sentenceDocument) {
      setNotice("Place the cursor between two non-empty parts of the sentence, then choose Split at cursor.");
      input.focus();
      return;
    }

    setSentenceDocument(updated);
    setNotice(illustrationsBySentence[id]
      ? `Split sentence ${position}. Its illustration stays with the first part; the new sentence has no illustration.`
      : `Split sentence ${position} into two sentences. The new sentence has no illustration.`);
  }

  function mergeSentenceWithPrevious(id: SentenceId, position: number) {
    const index = sentenceDocument.sentences.findIndex((sentence) => sentence.id === id);
    if (index <= 0) return;
    const previous = sentenceDocument.sentences[index - 1];
    const removedAssetId = illustrationsBySentence[id];
    const retainedAssetId = illustrationsBySentence[previous.id];
    if (removedAssetId && removedAssetId !== retainedAssetId) {
      const removedAsset = visuals.assets.find((asset) => asset.id === removedAssetId);
      const retainedAsset = visuals.assets.find((asset) => asset.id === retainedAssetId);
      const removedName = removedAsset?.name ?? "an assigned illustration";
      const retainedName = retainedAsset?.name ?? "no illustration";
      if (!window.confirm(`Sentence ${position} uses “${removedName}”, while the sentence above uses “${retainedName}”. Merging removes sentence ${position}'s assignment and keeps the sentence above's illustration. Continue?`)) return;
    }
    setSentenceDocument((current) => mergeWithPrevious(current, id));
    visualSelectionState.removeSentenceIllustration(id);
    setNotice(removedAssetId && removedAssetId !== retainedAssetId
      ? `Merged sentence ${position}; the previous sentence's illustration was kept.`
      : `Merged sentence ${position} with the previous sentence.`);
  }

  function deleteSentenceWithIllustration(id: SentenceId, position: number) {
    setSentenceDocument((current) => deleteSentence(current, id));
    visualSelectionState.removeSentenceIllustration(id);
    setNotice(`Deleted sentence ${position}. Its illustration assignment was removed; the image remains in the library.`);
  }

  const preparingAgain = replacement !== null;
  const editingLocked = preparingAgain || aiPending || speech.waiting || video.waiting;
  const sourceLocked = editingLocked || proposal !== null;
  const providerAvailable = providers.some((item) => item.id === selectedProvider && item.available);
  const sourceOverLimit = mode === "ai" && sourceDraft.length > MAX_SOURCE_LENGTH;
  const sentenceCount = sentenceDocument.sentences.length;
  const visualProblem = visuals.selectionProblem([
    ...(backgroundAssetId ? [{ id: backgroundAssetId, kind: "background" as const }] : []),
    ...Object.entries(illustrationsBySentence)
      .filter(([sentenceId]) => sentenceDocument.sentences.some((sentence) => sentence.id === sentenceId))
      .map(([, id]) => ({ id, kind: "illustration" as const })),
  ]);

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Shadowing Video Studio</p>
          <h1>Prepare your dialogue</h1>
          <p className="description">Shape your English dialogue into the sentences you want to practise.</p>
        </div>
        <p className="service-status" data-state={backendState} role="status">
          <span className="status-dot" aria-hidden="true" />
          {backendState === "checking" && "Checking local service…"}
          {backendState === "online" && "Local service connected"}
          {backendState === "offline" && "Local service unavailable · Editing still works"}
        </p>
      </header>

      {replacement !== null && (
        <section
          className="confirmation"
          role="alertdialog"
          aria-labelledby="replace-title"
          aria-describedby="replace-description"
          onKeyDown={(event) => {
            if (event.key === "Escape") setReplacement(null);
          }}
        >
          <div>
            <h2 id="replace-title">Replace the current sentence list?</h2>
            <p id="replace-description">
              {replacement.kind === "manual"
                ? "Preparing again replaces all current sentence edits and the original source snapshot with your source dialogue draft. Cancel to keep your current work and draft."
                : "Applying this reviewed AI proposal replaces all current sentence edits and the original source snapshot with the proposal's source. Cancel to keep your current work and the proposal."}
            </p>
          </div>
          <div className="confirmation-actions">
            <button
              ref={cancelButton}
              type="button"
              onClick={() => setReplacement(null)}
            >Cancel</button>
            <button
              type="button"
              className="primary-button"
              onClick={() => {
                if (replacement.kind === "manual") prepareSentences(replacement.source);
                else applyProposal(replacement.proposal);
              }}
            >{replacement.kind === "manual" ? "Replace and prepare" : "Replace and apply"}</button>
          </div>
        </section>
      )}

      <div className="workspace">
        <section className="panel source-panel" aria-labelledby="source-title">
          <div className="panel-heading">
            <span className="step-number" aria-hidden="true">01</span>
            <div><h2 id="source-title">Source dialogue</h2><p>Start with the original English text.</p></div>
          </div>
          <fieldset className="preparation-mode" disabled={sourceLocked}>
            <legend>Preparation mode</legend>
            <label>
              <input type="radio" name="preparation-mode" value="manual" checked={mode === "manual"}
                onChange={() => { setMode("manual"); setAiError(""); }} />
              Manual
            </label>
            <label>
              <input type="radio" name="preparation-mode" value="ai" checked={mode === "ai"}
                onChange={() => { setMode("ai"); setAiError(""); }} />
              AI-assisted
            </label>
          </fieldset>
          {mode === "ai" && (
            <div className="provider-field">
              <label htmlFor="ai-provider">AI provider</label>
              <select id="ai-provider" value={selectedProvider} disabled={sourceLocked || providerStatus !== "online"}
                onChange={(event) => {
                  const value = event.target.value;
                  if (value === "" || value === "deepseek" || value === "codex") setSelectedProvider(value);
                  setAiError("");
                }}>
                <option value="">Choose a provider</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id} disabled={!provider.available}>
                    {provider.label}{!provider.available ? " · Unavailable" : ""}
                  </option>
                ))}
              </select>
              {providerStatus === "checking" && <p className="field-help">Checking provider availability…</p>}
              {providerStatus === "offline" && <p className="field-help">Provider availability could not be loaded. Check the local service; manual editing still works.</p>}
              {providers.filter((provider) => !provider.available).map((provider) => (
                <p key={provider.id} className="field-help">{provider.reason}</p>
              ))}
              <p className="field-help">Prepare sends this dialogue to the selected provider. Review its proposal before applying it. No audio or video is generated.</p>
            </div>
          )}
          <label htmlFor="source-dialogue">Source dialogue</label>
          <textarea
            id="source-dialogue"
            className="source-input"
            rows={11}
            value={sourceDraft}
            disabled={sourceLocked}
            placeholder={"Hello there. How are you?\nI’m doing well, thank you."}
            aria-describedby="source-help"
            onChange={(event) => setSourceDraft(event.target.value)}
          />
          <p className="field-help" id="source-help">
            {mode === "manual"
              ? "Sentences are prepared locally from punctuation and line breaks. Review and adjust the result."
              : "Your source is preserved exactly. AI preparation accepts up to 20,000 characters."}
          </p>
          {sourceOverLimit && <p className="input-error" role="alert">This dialogue has {sourceDraft.length.toLocaleString("en-US")} characters. Shorten it to 20,000 or fewer for AI preparation; the full draft is preserved.</p>}
          <button
            ref={prepareButton}
            type="button"
            className="primary-button prepare-button"
            disabled={!sourceDraft.trim() || sourceLocked || sourceOverLimit || (mode === "ai" && !providerAvailable)}
            onClick={mode === "manual" ? requestPreparation : requestAiPreparation}
          >{mode === "manual" ? "Prepare sentences" : aiPending ? "Preparing AI proposal…" : "Prepare AI proposal"}</button>
          {aiPending && (
            <div className="pending-preparation" role="status">
              <p className="field-help">Preparing a proposal. Your source and current edits are protected while waiting.</p>
              <button type="button" onClick={() => stopWaiting()}>Stop waiting</button>
            </div>
          )}
          {aiError && <p className="input-error" role="alert">{aiError}</p>}
          {proposal && <p className="field-help">Apply or discard the proposal before changing the source or preparing again.</p>}

          {hasPrepared && (
            <details className="source-snapshot">
              <summary>Original source snapshot</summary>
              <p className="field-help">Saved when this list was prepared. Sentence edits do not change it.</p>
              <pre>{sentenceDocument.sourceText}</pre>
            </details>
          )}
          <p className="session-note">Work stays in this browser session. Refreshing or closing the page clears it.</p>
        </section>

        <section className="panel editor-panel" aria-labelledby="editor-title">
          <div className="panel-heading editor-heading">
            <span className="step-number" aria-hidden="true">02</span>
            <div>
              <h2 id="editor-title">Sentence editor</h2>
              <p>{sentenceCount} {sentenceCount === 1 ? "sentence" : "sentences"} · Manual mode</p>
            </div>
            <button
              type="button"
              disabled={editingLocked}
              onClick={() => applyOperation((current) => insertSentenceAfter(current, null), "Added a sentence at the end.")}
            >Add sentence</button>
          </div>

          {proposal && (
            <section className="proposal-review" aria-labelledby="proposal-title">
              <h3 id="proposal-title">Review AI proposal</h3>
              <p className="field-help">{proposal.provider === "deepseek" ? "DeepSeek" : "Codex CLI"} proposed {proposal.sentences.length} sentences. Check the wording and order. This proposal has not been applied and generates no media.</p>
              <ol className="proposal-list" aria-label="Proposed sentences">
                {proposal.sentences.map((text, index) => <li key={index}>{text}</li>)}
              </ol>
              <div className="proposal-actions">
                <button ref={applyButton} type="button" className="primary-button" disabled={preparingAgain}
                  onClick={requestProposalApplication}>Apply reviewed sentences</button>
                <button type="button" disabled={preparingAgain} onClick={() => {
                  setProposal(null);
                  setNotice("Discarded the AI proposal. Your source and current sentence edits are preserved.");
                }}>Discard proposal</button>
              </div>
            </section>
          )}

          <p className="editor-notice" role="status" aria-live="polite">{notice}</p>

          <BackgroundImageControls visuals={visuals} value={backgroundAssetId}
            onChange={visualSelectionState.setBackgroundAssetId} disabled={editingLocked} />
          {visualSelectionState.storageWarning && <p className="input-error" role="status">{visualSelectionState.storageWarning}</p>}

          <SpeechControls speech={speech} sentences={sentenceDocument.sentences}
            locked={editingLocked || video.outstanding || proposal !== null} />

          {sentenceCount === 0 ? (
            <div className="empty-state">
              <h3>Your sentence list starts here</h3>
              <p>Paste dialogue and prepare it, or add your first sentence.</p>
            </div>
          ) : (
            <>
              <p className="field-help split-help" id="split-help">
                To split, place the text cursor where the new sentence should begin, then choose Split at cursor.
              </p>
              <ol className="sentence-list">
                {sentenceDocument.sentences.map((sentence, index) => {
                  const position = index + 1;
                  return (
                    <li key={sentence.id} className="sentence-card" data-testid={`sentence-card-${position}`} data-sentence-id={sentence.id}>
                      <label htmlFor={`input-${sentence.id}`}>Sentence {position}</label>
                      <textarea
                        id={`input-${sentence.id}`}
                        rows={3}
                        value={sentence.text}
                        disabled={editingLocked}
                        aria-describedby="split-help"
                        ref={(input) => {
                          if (input) sentenceInputs.current.set(sentence.id, input);
                          else sentenceInputs.current.delete(sentence.id);
                        }}
                        onChange={(event) => setSentenceDocument((current) => updateSentenceText(current, sentence.id, event.target.value))}
                      />
                      <div className="sentence-actions" role="group" aria-label={`Actions for sentence ${position}`}>
                        <button type="button" disabled={editingLocked} aria-label={`Split sentence ${position} at cursor`} onClick={() => splitAtCursor(sentence.id, position)}>Split at cursor</button>
                        <button type="button" disabled={index === 0 || editingLocked} aria-label={`Merge sentence ${position} with previous`} onClick={() => mergeSentenceWithPrevious(sentence.id, position)}>Merge above</button>
                        <button type="button" disabled={editingLocked} aria-label={`Add after sentence ${position}`} onClick={() => applyOperation((current) => insertSentenceAfter(current, sentence.id), `Added a sentence after sentence ${position}.`)}>Add below</button>
                        <button type="button" disabled={index === 0 || editingLocked} aria-label={`Move sentence ${position} up`} onClick={() => applyOperation((current) => moveSentence(current, sentence.id, "up"), `Moved sentence ${position} up.`)}>Move up</button>
                        <button type="button" disabled={index === sentenceCount - 1 || editingLocked} aria-label={`Move sentence ${position} down`} onClick={() => applyOperation((current) => moveSentence(current, sentence.id, "down"), `Moved sentence ${position} down.`)}>Move down</button>
                        <button type="button" className="delete-button" disabled={editingLocked} aria-label={`Delete sentence ${position}`} onClick={() => deleteSentenceWithIllustration(sentence.id, position)}>Delete</button>
                      </div>
                      <SentenceIllustrationPicker visuals={visuals} sentenceId={sentence.id} position={position}
                        value={illustrationsBySentence[sentence.id] ?? null}
                        onChange={(assetId) => visualSelectionState.setSentenceIllustration(sentence.id, assetId)}
                        disabled={editingLocked} />
                      <SentenceSpeech sentence={sentence} position={position} selection={speech.selection} job={speech.job}
                        disabled={editingLocked || speech.outstanding || video.outstanding || proposal !== null || !speech.readiness?.available}
                        regenerate={() => { void speech.generate([sentence], true); }} />
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </section>
      </div>
      <VideoControls video={video} sentences={sentenceDocument.sentences} selection={speech.selection}
        locked={editingLocked || speech.outstanding || proposal !== null} backgroundAssetId={backgroundAssetId}
        illustrationsBySentence={illustrationsBySentence} visualProblem={visualProblem} />
    </main>
  );
}
