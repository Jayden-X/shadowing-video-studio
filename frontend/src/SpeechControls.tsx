import { useEffect, useState } from "react";
import type { SentenceItem } from "./domain/sentences";
import { currentSentenceAudio, sentenceAudioMismatch, speechInputProblem, type SpeechBinding, type SpeechJob, type SpeechSelection } from "./domain/speech";
import { speechAssetUrl } from "./speechApi";
import type { useSpeech } from "./useSpeech";

type SpeechState = ReturnType<typeof useSpeech>;

export function SpeechControls({ speech, sentences, locked, onGenerate }: {
  speech: SpeechState; sentences: readonly SentenceItem[]; locked: boolean; onGenerate?: () => void;
}) {
  const problem = speechInputProblem(sentences);
  const readyCount = sentences.filter((sentence) => currentSentenceAudio(sentence, speech.selection, speech.binding)).length;
  const capabilities = speech.capabilities;
  const unavailableReason = capabilities && !capabilities.available
    ? capabilities.reason ?? "The configured speech runtime does not currently offer voice selection."
    : capabilities && capabilities.voices.length === 0
      ? capabilities.reason ?? "The configured speech runtime has no selectable voices."
      : speech.readiness?.reason ?? (!capabilities ? "Speech availability could not be loaded. Check the local service; manual editing still works." : null);
  return (
    <section className="speech-panel" aria-labelledby="speech-title">
      <div className="speech-heading">
        <div><h3 id="speech-title">Sentence speech</h3><p className="field-help">Local {capabilities?.model ?? "TTS"} · {capabilities?.language ?? "English"}</p></div>
        <button type="button" className="primary-button" disabled={locked || speech.outstanding || speech.checking || !speech.readiness?.available || !capabilities?.available || !speech.binding || !!problem}
          onClick={() => { if (onGenerate) onGenerate(); else void speech.generate(sentences); }}>Generate speech</button>
      </div>
      <p className="field-help">Review the sentence list, then generate speech explicitly. Unchanged successful audio is reused.</p>
      {speech.checking ? <p className="field-help">Checking local speech runtime…</p>
        : unavailableReason && <p className="field-help">{unavailableReason}</p>}
      <div className="speech-voice-field">
        <label htmlFor="speech-voice">Speech voice</label>
        <select id="speech-voice" value={speech.selectedVoice} disabled={locked || speech.outstanding || speech.checking || !capabilities?.available || !capabilities || capabilities.voices.length === 0}
          onChange={(event) => speech.chooseVoice(event.target.value)}>
          <option value="">Choose a supported voice</option>
          {speech.selectedVoice && !capabilities?.voices.some((voice) => voice.id === speech.selectedVoice)
            && <option value={speech.selectedVoice}>{speech.selectedVoice} · Saved voice unavailable</option>}
          {capabilities?.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.label}</option>)}
        </select>
        {!speech.checking && !unavailableReason && !speech.binding && <p className="field-help">Select a supported voice before generating speech.</p>}
        {speech.notice && <p className="field-help" role="status">{speech.notice}</p>}
      </div>
      {!speech.waiting && <button type="button" disabled={speech.checking || speech.outstanding || locked} onClick={speech.refreshReadiness}>Check speech availability</button>}
      {problem && <p className="field-help">{problem}</p>}
      <p className="speech-progress" role="status" aria-live="polite">
        {speech.waiting ? `Generating speech · ${speech.job?.sentences.filter((sentence) => sentence.status === "ready").length ?? 0} of ${speech.job?.sentences.length ?? sentences.length} sentences ready`
          : `${readyCount} of ${sentences.length} current sentences have audio`}
      </p>
      {speech.waiting && <button type="button" onClick={() => speech.stopWaiting()}>Stop waiting for speech</button>}
      {!speech.waiting && speech.outstanding && <button type="button" onClick={speech.resumeMonitoring}>Resume speech monitoring</button>}
      {speech.error && <p className="input-error" role="alert">{speech.error}</p>}
      <p className="session-note">Speech job metadata stays in this service session. A service restart requires generation again; existing WAV files are preserved.</p>
    </section>
  );
}

export function SentenceSpeech({ sentence, position, selection, job, binding, disabled, regenerate }: {
  sentence: SentenceItem; position: number; selection: SpeechSelection; job: SpeechJob | null; binding: SpeechBinding | null;
  disabled: boolean; regenerate: () => void;
}) {
  const audio = currentSentenceAudio(sentence, selection, binding);
  const progress = job && binding && job.voice === binding.voice && job.configurationFingerprint === binding.configurationFingerprint
    ? job.sentences.find((item) => item.id === sentence.id && item.text === sentence.text) : undefined;
  const [playbackError, setPlaybackError] = useState(false);
  const mismatch = sentenceAudioMismatch(sentence, selection, binding);
  const priorAudio = Object.hasOwn(selection, sentence.id) ? selection[sentence.id] : undefined;
  const playableAudio = audio;
  useEffect(() => { setPlaybackError(false); }, [playableAudio?.assetId]);
  return (
    <div className="sentence-speech" role="group" aria-label={`Speech for sentence ${position}`}>
      <p className="field-help">
        {progress?.status === "generating" ? "Generating this sentence…"
          : progress?.status === "pending" ? "Waiting for generation…"
          : progress?.status === "failed" ? progress.error
          : audio ? `Audio ready · ${audio.durationSeconds.toFixed(1)} seconds${audio.reused ? " · Reused" : ""}`
          : mismatch === "text" ? "Text changed. Generate speech again before preview or video."
          : mismatch === "voice" ? `Saved audio uses ${priorAudio?.voice ?? "another"} voice. Generate speech with the selected voice before video.`
          : mismatch === "configuration" ? "Saved audio uses an earlier speech configuration. Generate speech again before video."
          : "No current audio. Generate speech after reviewing this sentence."}
      </p>
      {playableAudio && <audio key={playableAudio.assetId} controls preload="none" aria-label={`Preview sentence ${position}`}
        src={speechAssetUrl(playableAudio.assetId)} onError={() => setPlaybackError(true)} />}
      {playbackError && <p className="input-error" role="alert">This audio could not be played. Check the local service; regenerate after a service restart.</p>}
      <button type="button" disabled={disabled || !binding || !!speechInputProblem([sentence])} aria-label={`Regenerate speech for sentence ${position}`}
        onClick={regenerate}>Regenerate speech</button>
    </div>
  );
}
