import { useEffect, useState } from "react";
import type { SentenceItem } from "./domain/sentences";
import { currentSentenceAudio, speechInputProblem, type SpeechJob, type SpeechSelection } from "./domain/speech";
import { speechAssetUrl } from "./speechApi";
import type { useSpeech } from "./useSpeech";

type SpeechState = ReturnType<typeof useSpeech>;

export function SpeechControls({ speech, sentences, locked }: { speech: SpeechState; sentences: readonly SentenceItem[]; locked: boolean }) {
  const problem = speechInputProblem(sentences);
  const readyCount = sentences.filter((sentence) => currentSentenceAudio(sentence, speech.selection)).length;
  return (
    <section className="speech-panel" aria-labelledby="speech-title">
      <div className="speech-heading">
        <div><h3 id="speech-title">Sentence speech</h3><p className="field-help">Local Qwen3-TTS · Aiden · CPU / 0.6B</p></div>
        <button type="button" className="primary-button" disabled={locked || speech.outstanding || speech.checking || !speech.readiness?.available || !!problem}
          onClick={() => { void speech.generate(sentences); }}>Generate speech</button>
      </div>
      <p className="field-help">Review the sentence list, then generate speech explicitly. Unchanged successful audio is reused.</p>
      {speech.checking ? <p className="field-help">Checking local speech runtime…</p>
        : !speech.readiness?.available && <p className="field-help">{speech.readiness?.reason ?? "Speech availability could not be loaded. Check the local service; manual editing still works."}</p>}
      {!speech.waiting && <button type="button" disabled={speech.checking} onClick={speech.refreshReadiness}>Check speech availability</button>}
      {problem && <p className="field-help">{problem}</p>}
      <p className="speech-progress" role="status" aria-live="polite">
        {speech.waiting ? `Generating speech · ${speech.job?.sentences.filter((sentence) => sentence.status === "ready").length ?? 0} of ${speech.job?.sentences.length ?? sentences.length} sentences ready`
          : `${readyCount} of ${sentences.length} current sentences have audio`}
      </p>
      {speech.waiting && <button type="button" onClick={() => speech.stopWaiting()}>Stop waiting for speech</button>}
      {!speech.waiting && speech.outstanding && <button type="button" onClick={speech.resumeMonitoring}>Resume speech monitoring</button>}
      {speech.notice && <p className="field-help" role="status">{speech.notice}</p>}
      {speech.error && <p className="input-error" role="alert">{speech.error}</p>}
      <p className="session-note">Speech job metadata stays in this service session. A service restart requires generation again; existing WAV files are preserved.</p>
    </section>
  );
}

export function SentenceSpeech({ sentence, position, selection, job, disabled, regenerate }: {
  sentence: SentenceItem; position: number; selection: SpeechSelection; job: SpeechJob | null;
  disabled: boolean; regenerate: () => void;
}) {
  const audio = currentSentenceAudio(sentence, selection);
  const progress = job?.sentences.find((item) => item.id === sentence.id && item.text === sentence.text);
  const [playbackError, setPlaybackError] = useState(false);
  useEffect(() => { setPlaybackError(false); }, [audio?.assetId]);
  const stale = !audio && Object.hasOwn(selection, sentence.id);
  return (
    <div className="sentence-speech" role="group" aria-label={`Speech for sentence ${position}`}>
      <p className="field-help">
        {progress?.status === "generating" ? "Generating this sentence…"
          : progress?.status === "pending" ? "Waiting for generation…"
          : progress?.status === "failed" ? progress.error
          : audio ? `Audio ready · ${audio.durationSeconds.toFixed(1)} seconds${audio.reused ? " · Reused" : ""}`
          : stale ? "Text changed. Generate speech again before preview or video."
          : "No current audio. Generate speech after reviewing this sentence."}
      </p>
      {audio && <audio key={audio.assetId} controls preload="none" aria-label={`Preview sentence ${position}`}
        src={speechAssetUrl(audio.assetId)} onError={() => setPlaybackError(true)} />}
      {playbackError && <p className="input-error" role="alert">This audio could not be played. Check the local service; regenerate after a service restart.</p>}
      <button type="button" disabled={disabled || !!speechInputProblem([sentence])} aria-label={`Regenerate speech for sentence ${position}`}
        onClick={regenerate}>Regenerate speech</button>
    </div>
  );
}
