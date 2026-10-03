import { useEffect, useState } from "react";
import { getCompleteSpeechSelection, type SpeechSelection } from "./domain/speech";
import type { SentenceItem } from "./domain/sentences";
import { videoAssetUrl } from "./videoApi";
import type { useVideo } from "./useVideo";

export function VideoControls({ video, sentences, selection, locked }: {
  video: ReturnType<typeof useVideo>; sentences: readonly SentenceItem[]; selection: SpeechSelection; locked: boolean;
}) {
  const audio = getCompleteSpeechSelection(sentences, selection);
  const [selectedExport, setSelectedExport] = useState<string | null>(null);
  const [playbackError, setPlaybackError] = useState(false);
  useEffect(() => {
    setSelectedExport(video.exports.at(-1)?.assetId ?? null);
  }, [video.exports]);
  useEffect(() => { setPlaybackError(false); }, [selectedExport]);
  const selected = video.exports.find((item) => item.assetId === selectedExport);
  return (
    <section className="panel video-panel" aria-labelledby="video-title">
      <div className="panel-heading video-heading">
        <span className="step-number" aria-hidden="true">03</span>
        <div><h2 id="video-title">Shadowing video</h2><p>1080p · One sentence per page · Five-second practice pauses</p></div>
        <button type="button" className="primary-button" disabled={locked || video.waiting || video.outstanding || video.checking || !video.readiness?.available || audio === null}
          onClick={() => { if (audio) void video.generate(audio.map(({ id, text, assetId }) => ({ id, text, assetId }))); }}>Generate video</button>
      </div>
      <p className="field-help">Listen to the sentence audio before rendering. Each export freezes the current sentence order and audio; prior MP4 files are preserved.</p>
      {audio === null && <p className="field-help">Generate current audio for every sentence before rendering a video. Edited sentences need new speech.</p>}
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
        <p className="field-help">Exported snapshot · {selected.sentenceCount} sentences · {selected.durationSeconds.toFixed(1)} seconds</p>
        <video key={selected.assetId} controls preload="none" aria-label="Preview exported shadowing video"
          src={videoAssetUrl(selected.assetId)} onError={() => setPlaybackError(true)} />
        {playbackError && <p className="input-error" role="alert">This export could not be played. Check the local service; export links expire after a service restart.</p>}
        <a className="download-link" href={videoAssetUrl(selected.assetId, true)}>Download MP4</a>
      </div>}
      {video.exports.length > 0 && <ol className="export-list" aria-label="Exports in this session">
        {video.exports.map((output, index) => <li key={output.assetId}>
          <button type="button" onClick={() => setSelectedExport(output.assetId)}>Preview export {index + 1}</button>
          <a href={videoAssetUrl(output.assetId, true)}>Download export {index + 1}</a>
        </li>)}
      </ol>}
      <p className="session-note">Export links stay in this browser/service session. Download MP4 files before restarting; the local generated files are preserved.</p>
    </section>
  );
}
