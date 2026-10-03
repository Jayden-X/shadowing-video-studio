import { useEffect, useRef, useState } from "react";

import { getBackendHealth } from "./api";
import {
  createSentenceDocument,
  deleteSentence,
  insertSentenceAfter,
  mergeWithPrevious,
  moveSentence,
  splitSentence,
  updateSentenceText,
  type SentenceDocument,
  type SentenceId,
} from "./domain/sentences";

type BackendState = "checking" | "online" | "offline";

export default function App() {
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [sourceDraft, setSourceDraft] = useState("");
  const [sentenceDocument, setSentenceDocument] = useState(() => createSentenceDocument(""));
  const [hasPrepared, setHasPrepared] = useState(false);
  const [pendingSource, setPendingSource] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const sentenceInputs = useRef(new Map<SentenceId, HTMLTextAreaElement>());
  const prepareButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);

  useEffect(() => {
    let active = true;
    getBackendHealth()
      .then(() => {
        if (active) setBackendState("online");
      })
      .catch(() => {
        if (active) setBackendState("offline");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (pendingSource !== null) cancelButton.current?.focus();
    else if (wasConfirming.current) prepareButton.current?.focus();
    wasConfirming.current = pendingSource !== null;
  }, [pendingSource]);

  function prepareSentences(source: string) {
    const prepared = createSentenceDocument(source);
    setSentenceDocument(prepared);
    setHasPrepared(true);
    setPendingSource(null);
    setNotice(`Prepared ${prepared.sentences.length} sentences. Your source snapshot is saved below.`);
  }

  function requestPreparation() {
    if (hasPrepared || sentenceDocument.sentences.length > 0) {
      setPendingSource(sourceDraft);
      return;
    }
    prepareSentences(sourceDraft);
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
    setNotice(`Split sentence ${position} into two sentences.`);
  }

  const preparingAgain = pendingSource !== null;
  const sentenceCount = sentenceDocument.sentences.length;

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

      {preparingAgain && (
        <section
          className="confirmation"
          role="alertdialog"
          aria-labelledby="replace-title"
          aria-describedby="replace-description"
          onKeyDown={(event) => {
            if (event.key === "Escape") setPendingSource(null);
          }}
        >
          <div>
            <h2 id="replace-title">Replace the current sentence list?</h2>
            <p id="replace-description">
              Preparing again replaces all current sentence edits and the original source snapshot
              with your source dialogue draft. Cancel to keep your current work and draft.
            </p>
          </div>
          <div className="confirmation-actions">
            <button
              ref={cancelButton}
              type="button"
              onClick={() => setPendingSource(null)}
            >Cancel</button>
            <button
              type="button"
              className="primary-button"
              onClick={() => {
                prepareSentences(pendingSource);
              }}
            >Replace and prepare</button>
          </div>
        </section>
      )}

      <div className="workspace">
        <section className="panel source-panel" aria-labelledby="source-title">
          <div className="panel-heading">
            <span className="step-number" aria-hidden="true">01</span>
            <div><h2 id="source-title">Source dialogue</h2><p>Start with the original English text.</p></div>
          </div>
          <label htmlFor="source-dialogue">Source dialogue</label>
          <textarea
            id="source-dialogue"
            className="source-input"
            rows={11}
            value={sourceDraft}
            disabled={preparingAgain}
            placeholder={"Hello there. How are you?\nI’m doing well, thank you."}
            aria-describedby="source-help"
            onChange={(event) => setSourceDraft(event.target.value)}
          />
          <p className="field-help" id="source-help">
            Sentences are prepared locally from punctuation and line breaks. Review and adjust the result.
          </p>
          <button
            ref={prepareButton}
            type="button"
            className="primary-button prepare-button"
            disabled={!sourceDraft.trim() || preparingAgain}
            onClick={requestPreparation}
          >Prepare sentences</button>

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
              disabled={preparingAgain}
              onClick={() => applyOperation((current) => insertSentenceAfter(current, null), "Added a sentence at the end.")}
            >Add sentence</button>
          </div>

          <p className="editor-notice" role="status" aria-live="polite">{notice}</p>

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
                        disabled={preparingAgain}
                        aria-describedby="split-help"
                        ref={(input) => {
                          if (input) sentenceInputs.current.set(sentence.id, input);
                          else sentenceInputs.current.delete(sentence.id);
                        }}
                        onChange={(event) => setSentenceDocument((current) => updateSentenceText(current, sentence.id, event.target.value))}
                      />
                      <div className="sentence-actions" role="group" aria-label={`Actions for sentence ${position}`}>
                        <button type="button" disabled={preparingAgain} aria-label={`Split sentence ${position} at cursor`} onClick={() => splitAtCursor(sentence.id, position)}>Split at cursor</button>
                        <button type="button" disabled={index === 0 || preparingAgain} aria-label={`Merge sentence ${position} with previous`} onClick={() => applyOperation((current) => mergeWithPrevious(current, sentence.id), `Merged sentence ${position} with the previous sentence.`)}>Merge above</button>
                        <button type="button" disabled={preparingAgain} aria-label={`Add after sentence ${position}`} onClick={() => applyOperation((current) => insertSentenceAfter(current, sentence.id), `Added a sentence after sentence ${position}.`)}>Add below</button>
                        <button type="button" disabled={index === 0 || preparingAgain} aria-label={`Move sentence ${position} up`} onClick={() => applyOperation((current) => moveSentence(current, sentence.id, "up"), `Moved sentence ${position} up.`)}>Move up</button>
                        <button type="button" disabled={index === sentenceCount - 1 || preparingAgain} aria-label={`Move sentence ${position} down`} onClick={() => applyOperation((current) => moveSentence(current, sentence.id, "down"), `Moved sentence ${position} down.`)}>Move down</button>
                        <button type="button" className="delete-button" disabled={preparingAgain} aria-label={`Delete sentence ${position}`} onClick={() => applyOperation((current) => deleteSentence(current, sentence.id), `Deleted sentence ${position}.`)}>Delete</button>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
