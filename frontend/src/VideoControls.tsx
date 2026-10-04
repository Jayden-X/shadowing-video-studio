import { useEffect, useState } from "react";
import { getCompleteSpeechSelection, type SpeechBinding, type SpeechSelection } from "./domain/speech";
import type { SentenceItem } from "./domain/sentences";
import { videoAssetUrl, type VideoSentence } from "./videoApi";
import type { useVideo } from "./useVideo";
import type { ProjectHistoryEntry } from "./projectApi";

export function VideoControls({ video, sentences, selection, binding, locked, backgroundAssetId = null,
  illustrationsBySentence = {}, visualProblem = null, history = [], onGenerate }: {
  video: ReturnType<typeof useVideo>; sentences: readonly SentenceItem[]; selection: SpeechSelection; binding: SpeechBinding | null; locked: boolean;
  backgroundAssetId?: string | null; illustrationsBySentence?: Readonly<Record<string, string>>; visualProblem?: string | null;
  history?: readonly ProjectHistoryEntry[]; onGenerate?: (sentences: readonly VideoSentence[]) => void;
}) {
  const audio = getCompleteSpeechSelection(sentences, selection, binding);
  const [selectedExport, setSelectedExport] = useState<string | null>(null);
  const [playbackError, setPlaybackError] = useState(false);
  useEffect(() => {
    setSelectedExport([...history].reverse().find((item) => item.available)?.id ?? null);
  }, [history]);
  useEffect(() => { setPlaybackError(false); }, [selectedExport]);
  const selected = history.find((item) => item.id === selectedExport && item.available);
  const selectedSentences = selected?.snapshot?.editor.document.sentences ?? [];
  const selectedVoice = typeof selected?.snapshot?.request.voice === "string" ? selected.snapshot.request.voice : selected?.snapshot?.editor.voice;
  return (
    <section className="panel video-panel" aria-labelledby="video-title">
      <div className="panel-heading video-heading">
        <span className="step-number" aria-hidden="true">03</span>
        <div><h2 id="video-title">Shadowing video</h2><p>1080p · One sentence per page · Five-second practice pauses</p></div>
        <button type="button" className="primary-button" disabled={locked || video.waiting || video.outstanding || video.checking || !video.readiness?.available || !binding || audio === null || !!visualProblem}
          onClick={() => { if (audio && binding) {
            const frozenAudio = audio.map(({ id, text, assetId }) => ({ id, text, assetId, illustrationAssetId: illustrationsBySentence[id] ?? null }));
            if (onGenerate) onGenerate(frozenAudio);
            else void video.generate(frozenAudio, binding, backgroundAssetId);
          } }}>Generate video</button>
      </div>
      <p className="field-help">Listen to the sentence audio before rendering. Each export freezes the current sentence order and audio; prior MP4 files are preserved.</p>
      {audio === null && <p className="field-help">Generate current audio for every sentence before rendering a video. Edited sentences need new speech.</p>}
      {visualProblem && <p className="input-error" role="alert">{visualProblem}</p>}
      {video.checking ? <p className="field-help">Checking local video renderer…</p>
        : !video.readiness?.available && <p className="field-help">{video.readiness?.reason ?? "Video availability could not be loaded. Check the local service."}</p>}
      {!video.waiting && <button type="button" disabled={video.checking} onClick={video.refreshReadiness}>Check video availability</button>}
      {video.waiting && <div className="video-progress" role="status" aria-live="polite">
        <p>Rendering video · {video.job?.completedSentences ?? 0} of {video.job?.totalSentences ?? sentences.length} pages complete</p>
        <button type="button" onClick={() => video.stopWaiting()}>Stop waiting for video</button>
      </div>}
      {!video.waiting && video.outstanding && <button type="button" onClick={video.resumeMonitoring}>Resume video monitoring</button>}
      {video.notice && <p className="field-help" role="status">{video.notice}</p>}
      {video.error && <p className="input-error" role="alert">{video.error}</p>}
      {selected && <div className="video-preview">
        <h3>Export preview</h3>
        <p className="field-help">{new Date(selected.createdAt).toLocaleString()} · {selectedSentences.length} sentences
          {selected.durationSeconds ? ` · ${selected.durationSeconds.toFixed(1)} seconds` : ""}{selectedVoice ? ` · ${selectedVoice}` : ""}</p>
        <video key={selected.id} controls preload="none" aria-label="Preview exported shadowing video"
          src={videoAssetUrl(selected.id)} onError={() => setPlaybackError(true)} />
        {playbackError && <p className="input-error" role="alert">This export could not be played. Check the local service and its registered media file.</p>}
        <a className="download-link" href={videoAssetUrl(selected.id, true)}>Download MP4</a>
        <details className="frozen-video-snapshot">
          <summary>Frozen video inputs</summary>
          <p className="field-help">Voice: {selectedVoice ?? "Unavailable"} · Background: {selected.snapshot?.editor.backgroundAssetId ?? "None"}</p>
          <ol className="proposal-list">{selectedSentences.map((sentence) => <li key={sentence.id}>{sentence.text}</li>)}</ol>
          {selected.reason && <p className="input-error">{selected.reason}</p>}
        </details>
      </div>}
      <section className="project-history" aria-labelledby="video-history-title">
        <h3 id="video-history-title">Video history</h3>
        {history.length === 0 ? <p className="field-help">No completed video outputs for this project yet.</p> : <ol className="export-list" aria-label="Saved video history">
          {history.map((output, index) => <li key={output.id}>
            <span>Export {index + 1} · {new Date(output.createdAt).toLocaleString()}
              {output.durationSeconds ? ` · ${output.durationSeconds.toFixed(1)} seconds` : ""}</span>
            {output.available
              ? <><button type="button" onClick={() => setSelectedExport(output.id)}>Preview</button>
                <a href={videoAssetUrl(output.id, true)}>Download MP4</a></>
              : <span className="input-error">Unavailable{output.reason ? ` · ${output.reason}` : ""}</span>}
          </li>)}
        </ol>}
      </section>
      <p className="session-note">History is loaded from the saved project and keeps each video's original input snapshot.</p>
    </section>
  );
}
