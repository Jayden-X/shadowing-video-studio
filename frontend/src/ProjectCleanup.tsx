import { useEffect, useRef, useState } from "react";

import { speechAssetUrl } from "./speechApi";
import { videoAssetUrl } from "./videoApi";
import {
  CleanupApiError,
  executeProjectCleanup,
  formatResourceBytes,
  getProjectCleanupResult,
  getRetainedProjectResources,
  previewProjectCleanup,
  type ProjectCleanupMode,
  type ProjectCleanupPreview,
  type ProjectCleanupResult,
  type RetainedProjectResources,
} from "./cleanupApi";
import type { ProjectRecord } from "./projectApi";

type CleanupDialog = {
  project: ProjectRecord;
  mode: ProjectCleanupMode;
  preview: ProjectCleanupPreview | null;
  loadingPreview: boolean;
  submitting: boolean;
  attempted: boolean;
  error: string;
};

const modeLabels: Record<ProjectCleanupMode, string> = {
  project_only: "Delete project only",
  intermediate: "Delete project and intermediate resources",
  all: "Delete project and all related resources",
};

function cleanupSummary(mode: ProjectCleanupMode): string {
  if (mode === "project_only") return "Removes the project and its history. Keeps generated WAV audio, render intermediates and MP4 outputs.";
  if (mode === "intermediate") return "Removes the project, generated WAV audio and render intermediates. Keeps final MP4 outputs.";
  return "Removes the project, generated WAV audio, render intermediates and final MP4 outputs.";
}

function RetainedProject({ project, onRetry, retrying, retryError, disabled }: {
  project: RetainedProjectResources;
  onRetry: () => void;
  retrying: boolean;
  retryError: string;
  disabled: boolean;
}) {
  const [videoErrors, setVideoErrors] = useState<Record<string, boolean>>({});
  const [audioErrors, setAudioErrors] = useState<Record<string, boolean>>({});
  const needsRetry = project.cleanup.status === "partial" || project.cleanup.status === "pending";
  return (
    <article className="retained-project" aria-labelledby={`retained-${project.projectId}`}>
      <div className="retained-project-heading">
        <div>
          <h3 id={`retained-${project.projectId}`}>{project.projectName}</h3>
          <p className="field-help">Deleted {new Date(project.deletedAt).toLocaleString()} · {modeLabels[project.mode]}</p>
        </div>
        <span className="cleanup-status" data-state={project.cleanup.status}>{project.cleanup.status}</span>
      </div>
      <p className="field-help">Removed {project.cleanup.deletedFiles} files · {project.cleanup.failedFiles} failed</p>
      {project.cleanup.error && <p className="input-error" role="status">{project.cleanup.error}</p>}
      {project.cleanup.warnings.map((warning, index) => <p className="field-help" key={`${project.projectId}-warning-${index}`}>{warning}</p>)}
      {needsRetry && <div className="retained-retry">
        <button type="button" disabled={retrying || disabled} onClick={onRetry}>{retrying ? "Retrying cleanup…" : "Retry failed cleanup"}</button>
        <span className="field-help">Retry uses the same cleanup operation and keeps any resources already retained.</span>
        {retryError && <p className="input-error" role="alert">{retryError}</p>}
      </div>}
      <div className="retained-resource-grid">
        <section aria-label={`Retained audio for ${project.projectName}`}>
          <h4>Retained audio</h4>
          {project.audio.length === 0 ? <p className="field-help">No retained audio files.</p> : <ul className="retained-audio-list">
            {project.audio.map((audio) => <li key={audio.id}>
              <p><strong>{audio.sentenceId}</strong> · {audio.text}</p>
              <p className="field-help">{audio.voice} · {audio.durationSeconds.toFixed(1)} seconds · {formatResourceBytes(audio.sizeBytes)}</p>
              {audio.available
                ? <audio controls preload="none" aria-label={`Preview retained audio ${audio.sentenceId}`} src={speechAssetUrl(audio.id)}
                  onError={() => setAudioErrors((current) => ({ ...current, [audio.id]: true }))} />
                : <p className="input-error">Unavailable{audio.reason ? ` · ${audio.reason}` : ""}</p>}
              {audioErrors[audio.id] && <p className="input-error" role="alert">This audio could not be played from the local service.</p>}
            </li>)}
          </ul>}
        </section>
        <section aria-label={`Retained videos for ${project.projectName}`}>
          <h4>Retained videos</h4>
          {project.videos.length === 0 ? <p className="field-help">No retained MP4 files.</p> : <ul className="retained-video-list">
            {project.videos.map((video) => <li key={video.id}>
              <p>{new Date(video.createdAt).toLocaleString()}
                {video.durationSeconds ? ` · ${video.durationSeconds.toFixed(1)} seconds` : ""}
                {video.sizeBytes !== null ? ` · ${formatResourceBytes(video.sizeBytes)}` : ""}</p>
              {video.available
                ? <>
                  <video controls preload="none" aria-label={`Preview retained video ${new Date(video.createdAt).toLocaleString()}`}
                    src={videoAssetUrl(video.id)} onError={() => setVideoErrors((current) => ({ ...current, [video.id]: true }))} />
                  <a className="download-link" href={videoAssetUrl(video.id, true)}>Download MP4</a>
                </>
                : <p className="input-error">Unavailable{video.reason ? ` · ${video.reason}` : ""}</p>}
              {videoErrors[video.id] && <p className="input-error" role="alert">This video could not be played from the local service.</p>}
            </li>)}
          </ul>}
        </section>
      </div>
    </article>
  );
}

export function RetainedResources({ refreshSignal = 0, disabled = false }: { refreshSignal?: number; disabled?: boolean }) {
  const [retained, setRetained] = useState<RetainedProjectResources[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [reload, setReload] = useState(0);
  const [retryingProjectId, setRetryingProjectId] = useState<string | null>(null);
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError("");
    getRetainedProjectResources(controller.signal).then((items) => {
      setRetained(items);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setLoadError(error instanceof CleanupApiError ? error.message : "Retained project resources could not be loaded.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [refreshSignal, reload]);

  async function retryRetained(project: RetainedProjectResources) {
    if (retryingProjectId || disabled) return;
    setRetryingProjectId(project.projectId);
    setRetryErrors((current) => ({ ...current, [project.projectId]: "" }));
    try {
      const result = await executeProjectCleanup(project.projectId, project.cleanup.operationToken);
      if (result.status === "completed") setRetained((current) => current.filter((item) => item.projectId !== project.projectId));
      else setRetained((current) => current.map((item) => item.projectId === project.projectId ? { ...item, cleanup: result } : item));
      setReload((value) => value + 1);
    } catch (error: unknown) {
      let confirmed: ProjectCleanupResult | null = null;
      try {
        confirmed = await getProjectCleanupResult(project.projectId, project.cleanup.operationToken);
      } catch {
        try {
          const resources = await getRetainedProjectResources();
          confirmed = resources.find((item) => item.projectId === project.projectId
            && item.cleanup.operationToken === project.cleanup.operationToken)?.cleanup ?? null;
        } catch {
          // Keep the same-token retry available when the local service cannot reconcile yet.
        }
      }
      if (confirmed) {
        if (confirmed.status === "completed") setRetained((current) => current.filter((item) => item.projectId !== project.projectId));
        else setRetained((current) => current.map((item) => item.projectId === project.projectId ? { ...item, cleanup: confirmed! } : item));
        setReload((value) => value + 1);
      } else {
        setRetryErrors((current) => ({ ...current, [project.projectId]: error instanceof CleanupApiError || error instanceof Error
          ? error.message : "Cleanup could not be confirmed. Retry the same operation to check its result." }));
      }
    } finally {
      setRetryingProjectId(null);
    }
  }

  return <section className="retained-resources" aria-labelledby="retained-resources-title">
    <div className="retained-resources-heading">
      <div><h2 id="retained-resources-title">Retained resources</h2>
        <p className="field-help">Resources kept after project cleanup stay grouped by their original project.</p></div>
      <button type="button" disabled={loading} onClick={() => setReload((value) => value + 1)}>Refresh</button>
    </div>
    {loading && <p className="field-help" role="status">Loading retained resources…</p>}
    {loadError && <p className="input-error" role="alert">{loadError}</p>}
    {!loading && !loadError && retained.length === 0 && <p className="field-help">No retained resources are registered.</p>}
    {retained.map((item) => <RetainedProject key={item.projectId} project={item}
      onRetry={() => { void retryRetained(item); }} retrying={retryingProjectId === item.projectId}
      retryError={retryErrors[item.projectId] ?? ""} disabled={disabled} />)}
  </section>;
}

export function ProjectCleanup({ activeProject, disabled, flushSave, onDialogOpenChange, onProjectRemoved, onRefreshProject }: {
  activeProject: ProjectRecord | null;
  disabled: boolean;
  flushSave: () => Promise<ProjectRecord | null>;
  onDialogOpenChange: (open: boolean) => void;
  onProjectRemoved: (projectId: string, result: ProjectCleanupResult) => void;
  onRefreshProject: (projectId: string) => Promise<void>;
}) {
  const [dialog, setDialog] = useState<CleanupDialog | null>(null);
  const requestSequence = useRef(0);
  const modeSelect = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (dialog) modeSelect.current?.focus();
  }, [dialog !== null]);

  function updateDialog(next: CleanupDialog | null) {
    setDialog(next);
    onDialogOpenChange(next !== null);
  }

  async function startCleanup() {
    if (!activeProject || disabled || dialog) return;
    const initial: CleanupDialog = { project: activeProject, mode: "project_only", preview: null,
      loadingPreview: true, submitting: false, attempted: false, error: "" };
    const sequence = ++requestSequence.current;
    updateDialog(initial);
    try {
      const saved = await flushSave();
      if (!saved || saved.id !== initial.project.id) throw new Error("The project could not be saved before cleanup preview.");
      const preview = await previewProjectCleanup(saved, initial.mode);
      if (requestSequence.current === sequence) updateDialog({ ...initial, project: saved, preview, loadingPreview: false });
    } catch (error: unknown) {
      if (requestSequence.current === sequence) updateDialog({ ...initial, loadingPreview: false,
        error: error instanceof CleanupApiError || error instanceof Error ? error.message : "The cleanup preview could not be loaded." });
    }
  }

  async function changeMode(mode: ProjectCleanupMode) {
    if (!dialog || dialog.loadingPreview || dialog.submitting || dialog.attempted) return;
    const current = dialog;
    const sequence = ++requestSequence.current;
    updateDialog({ ...current, mode, preview: null, loadingPreview: true, error: "" });
    try {
      const saved = await flushSave();
      if (!saved || saved.id !== current.project.id) throw new Error("The project could not be saved before cleanup preview.");
      const preview = await previewProjectCleanup(saved, mode);
      if (requestSequence.current === sequence) updateDialog({ ...current, project: saved, mode, preview, loadingPreview: false, error: "" });
    } catch (error: unknown) {
      if (requestSequence.current === sequence) updateDialog({ ...current, mode, preview: null, loadingPreview: false,
        error: error instanceof CleanupApiError || error instanceof Error ? error.message : "The cleanup preview could not be loaded." });
    }
  }

  async function previewAgain() {
    if (!dialog || dialog.submitting) return;
    const current = dialog;
    const sequence = ++requestSequence.current;
    updateDialog({ ...current, preview: null, loadingPreview: true, error: "", attempted: false });
    try {
      const saved = await flushSave();
      if (!saved || saved.id !== current.project.id) throw new Error("The project could not be saved before cleanup preview.");
      const preview = await previewProjectCleanup(saved, current.mode);
      if (requestSequence.current === sequence) updateDialog({ ...current, project: saved, preview, loadingPreview: false, error: "", attempted: false });
    } catch (error: unknown) {
      if (requestSequence.current === sequence) updateDialog({ ...current, loadingPreview: false,
        error: error instanceof CleanupApiError || error instanceof Error ? error.message : "The cleanup preview could not be loaded." });
    }
  }

  async function confirmCleanup() {
    if (!dialog || dialog.loadingPreview || dialog.submitting || !dialog.preview) return;
    const current = dialog;
    const preview = current.preview;
    if (!preview) return;
    const sequence = ++requestSequence.current;
    updateDialog({ ...current, submitting: true, attempted: true, error: "" });
    try {
      const result = await executeProjectCleanup(current.project.id, preview.planToken);
      if (requestSequence.current !== sequence) return;
      if (result.status === "pending") {
        updateDialog(null);
        onProjectRemoved(current.project.id, result);
      } else {
        updateDialog(null);
        onProjectRemoved(current.project.id, result);
      }
    } catch (error: unknown) {
      if (requestSequence.current !== sequence) return;
      const requestError = error instanceof CleanupApiError || error instanceof Error
        ? error.message : "Cleanup could not be confirmed. Retry the same operation to check its result.";
      let confirmed: ProjectCleanupResult | null = null;
      let isUnconfirmedPlan = error instanceof CleanupApiError && error.status === 409;
      try {
        confirmed = await getProjectCleanupResult(current.project.id, preview.planToken);
      } catch (statusError: unknown) {
        isUnconfirmedPlan ||= statusError instanceof CleanupApiError && statusError.status === 409;
      }
      if (!confirmed) {
        try {
          const resources = await getRetainedProjectResources();
          const retainedCleanup = resources.find((item) => item.projectId === current.project.id
            && item.cleanup.operationToken === preview.planToken)?.cleanup;
          if (retainedCleanup) confirmed = retainedCleanup;
        } catch {
          // The explicit same-token retry remains available if reconciliation is temporarily offline.
        }
      }
      if (requestSequence.current !== sequence) return;
      if (confirmed) {
        if (confirmed.status === "pending") {
          updateDialog(null);
          onProjectRemoved(current.project.id, confirmed);
        } else {
          updateDialog(null);
          onProjectRemoved(current.project.id, confirmed);
        }
      } else if (isUnconfirmedPlan) {
        updateDialog({ ...current, preview: null, loadingPreview: false, submitting: false, attempted: false, error: requestError });
      } else {
        updateDialog({ ...current, submitting: false, attempted: true, error: requestError });
      }
    }
  }

  function closeDialog() {
    if (!dialog || dialog.submitting) return;
    const current = dialog;
    requestSequence.current += 1;
    updateDialog(null);
    if (current.attempted) {
      void onRefreshProject(current.project.id);
    }
  }

  return (
    <>
      <section className="cleanup-toolbar" aria-label="Project cleanup">
        <button type="button" className="delete-button" disabled={!activeProject || disabled}
          onClick={() => { void startCleanup(); }}>Delete project…</button>
        {disabled && activeProject && <span className="field-help">Wait for local work and project saves to finish before cleanup.</span>}
      </section>

      {dialog && <div className="cleanup-backdrop">
        <section className="cleanup-dialog" role="alertdialog" aria-modal="true" aria-labelledby="cleanup-title"
          aria-describedby="cleanup-description" onKeyDown={(event) => {
            if (event.key === "Escape" && !dialog.submitting) closeDialog();
          }}>
          <h2 id="cleanup-title">Delete “{dialog.project.name}”?</h2>
          <p id="cleanup-description">Choose what to remove. Shared background and illustration originals stay in the visual library; project render copies follow the selected cleanup mode.</p>
          <label htmlFor="cleanup-mode">Cleanup mode</label>
          <select id="cleanup-mode" ref={modeSelect} value={dialog.mode}
            disabled={dialog.loadingPreview || dialog.submitting || dialog.attempted}
            onChange={(event) => { void changeMode(event.target.value as ProjectCleanupMode); }}>
            {Object.entries(modeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <p className="field-help">{cleanupSummary(dialog.mode)}</p>
          {dialog.loadingPreview && <p className="field-help" role="status">Saving the latest project revision and calculating the cleanup preview…</p>}
          {dialog.preview && <div className="cleanup-preview" aria-label="Cleanup preview">
            <p><strong>Project</strong> · {dialog.preview.projectName} · revision {dialog.preview.revision}</p>
            <p><strong>Will delete</strong> · {dialog.preview.deleteFiles.count} files · {formatResourceBytes(dialog.preview.deleteFiles.bytes)}</p>
            <p><strong>Will retain</strong> · {dialog.preview.retainFiles.count} files · {formatResourceBytes(dialog.preview.retainFiles.bytes)}</p>
            {dialog.preview.warnings.map((warning, index) => <p className="cleanup-warning" key={`preview-warning-${index}`}>{warning}</p>)}
          </div>}
          {dialog.error && <p className="input-error" role="alert">{dialog.error}</p>}
          <div className="confirmation-actions">
            <button type="button" disabled={dialog.submitting} onClick={closeDialog}>{dialog.attempted ? "Close and refresh project" : "Cancel"}</button>
            {!dialog.attempted && <button type="button" disabled={dialog.loadingPreview || dialog.submitting} onClick={() => { void previewAgain(); }}>Refresh preview</button>}
            <button type="button" className="delete-button" disabled={dialog.loadingPreview || dialog.submitting || !dialog.preview}
              onClick={() => { void confirmCleanup(); }}>{dialog.attempted ? "Retry same cleanup" : "Confirm delete"}</button>
          </div>
        </section>
      </div>}
    </>
  );
}
