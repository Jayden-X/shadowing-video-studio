import { useEffect, useRef, useState } from "react";

import { formatResourceBytes } from "./cleanupApi";
import type { useVisuals } from "./useVisuals";
import {
  executeVisualAssetCleanup,
  getVisualAssetCleanupResult,
  getVisualCleanupOperations,
  previewVisualAssetCleanup,
  renameVisualAsset,
  visualAssetUrl,
  VisualApiError,
  type VisualAsset,
  type VisualCleanupPreview,
  type VisualCleanupResult,
} from "./visualApi";

type VisualLibraryState = ReturnType<typeof useVisuals>;
type CleanupTarget = Pick<VisualAsset, "id" | "name"> & Partial<Pick<VisualAsset, "kind" | "width" | "height" | "sizeBytes">>;
type ImageCleanupDialog = {
  asset: CleanupTarget;
  preview: VisualCleanupPreview | null;
  operationToken: string | null;
  result: VisualCleanupResult | null;
  loadingPreview: boolean;
  submitting: boolean;
  attempted: boolean;
  error: string;
};

function resultMessage(result: VisualCleanupResult): string {
  if (result.status === "partial") return `${result.name} cleanup stopped with ${result.failedFiles} failed file deletions. Retry this same cleanup operation to continue.`;
  return `${result.name} cleanup is pending. Retry this same cleanup operation to check progress.`;
}

export function VisualLibraryCleanup({ visuals, selectedAssetIds, projectName, busy, onDialogOpenChange }: {
  visuals: VisualLibraryState;
  selectedAssetIds: ReadonlySet<string>;
  projectName: string;
  busy: boolean;
  onDialogOpenChange: (open: boolean) => void;
}) {
  const [dialog, setDialog] = useState<ImageCleanupDialog | null>(null);
  const [operations, setOperations] = useState<VisualCleanupResult[]>([]);
  const [localOperations, setLocalOperations] = useState<Record<string, VisualCleanupResult>>({});
  const [operationsLoading, setOperationsLoading] = useState(true);
  const [operationsError, setOperationsError] = useState("");
  const [reloadOperations, setReloadOperations] = useState(0);
  const [editingAssetId, setEditingAssetId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState("");
  const [renaming, setRenaming] = useState(false);
  const requestSequence = useRef(0);
  const dialogHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setOperationsLoading(true);
    setOperationsError("");
    getVisualCleanupOperations(controller.signal).then((items) => {
      if (!controller.signal.aborted) setOperations(items);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setOperationsError(error instanceof VisualApiError ? error.message : "Image cleanup history could not be loaded.");
    }).finally(() => {
      if (!controller.signal.aborted) setOperationsLoading(false);
    });
    return () => controller.abort();
  }, [reloadOperations]);

  function updateDialog(next: ImageCleanupDialog | null) {
    setDialog(next);
    onDialogOpenChange(next !== null);
  }

  function rememberOperation(result: VisualCleanupResult) {
    setLocalOperations((current) => ({ ...current, [result.assetId]: result }));
    setReloadOperations((value) => value + 1);
  }

  function forgetOperation(assetId: string) {
    setLocalOperations((current) => { const next = { ...current }; delete next[assetId]; return next; });
    setOperations((current) => current.filter((item) => item.assetId !== assetId));
    setReloadOperations((value) => value + 1);
  }

  async function startPreview(asset: VisualAsset) {
    if (busy || visuals.checking || visuals.error || dialog) return;
    const initial: ImageCleanupDialog = { asset, preview: null, operationToken: null, result: null,
      loadingPreview: true, submitting: false, attempted: false, error: "" };
    const sequence = ++requestSequence.current;
    updateDialog(initial);
    try {
      const preview = await previewVisualAssetCleanup(asset.id);
      if (requestSequence.current === sequence) {
        updateDialog({ ...initial, preview, operationToken: preview.planToken, loadingPreview: false });
        dialogHeading.current?.focus();
      }
    } catch (error: unknown) {
      if (requestSequence.current === sequence) updateDialog({ ...initial, loadingPreview: false,
        error: error instanceof VisualApiError || error instanceof Error ? error.message : "The image cleanup preview could not be loaded." });
    }
  }

  async function refreshPreview() {
    if (!dialog || dialog.submitting) return;
    const current = dialog;
    const sequence = ++requestSequence.current;
    updateDialog({ ...current, preview: null, operationToken: null, result: null, loadingPreview: true, attempted: false, error: "" });
    try {
      const preview = await previewVisualAssetCleanup(current.asset.id);
      if (requestSequence.current === sequence) updateDialog({ ...current, preview, operationToken: preview.planToken,
        result: null, loadingPreview: false, attempted: false, error: "" });
    } catch (error: unknown) {
      if (requestSequence.current === sequence) updateDialog({ ...current, preview: null, operationToken: null,
        loadingPreview: false, attempted: false,
        error: error instanceof VisualApiError || error instanceof Error ? error.message : "The image cleanup preview could not be loaded." });
    }
  }

  async function confirmCleanup() {
    if (!dialog || dialog.submitting || dialog.loadingPreview || !dialog.operationToken) return;
    const current = dialog;
    const token = current.operationToken;
    if (!token) return;
    const sequence = ++requestSequence.current;
    updateDialog({ ...current, submitting: true, attempted: true, error: "" });
    try {
      const result = await executeVisualAssetCleanup(current.asset.id, token);
      if (requestSequence.current !== sequence) return;
      if (result.name !== current.asset.name) throw new VisualApiError("The local service returned invalid image cleanup data.");
      if (result.status === "completed") {
        forgetOperation(current.asset.id);
        updateDialog(null);
        visuals.refresh();
      } else {
        rememberOperation(result);
        updateDialog({ ...current, result, submitting: false, attempted: true, error: result.error ?? resultMessage(result) });
      }
    } catch (error: unknown) {
      if (requestSequence.current !== sequence) return;
      const requestError = error instanceof VisualApiError || error instanceof Error
        ? error.message : "The image cleanup result could not be confirmed. Retry the same token to check its result.";
      let confirmed: VisualCleanupResult | null = null;
      try { confirmed = await getVisualAssetCleanupResult(current.asset.id, token); } catch { /* Reconcile from the operations list below. */ }
      if (requestSequence.current !== sequence) return;
      if (confirmed && confirmed.name !== current.asset.name) confirmed = null;
      if (confirmed?.status === "completed") {
        forgetOperation(current.asset.id);
        updateDialog(null);
        visuals.refresh();
      } else if (confirmed) {
        rememberOperation(confirmed);
        updateDialog({ ...current, result: confirmed, submitting: false, attempted: true, error: requestError });
      } else {
        try {
          const latest = await getVisualCleanupOperations();
          const recovered = latest.find((item) => item.assetId === current.asset.id && item.operationToken === token);
          if (recovered) confirmed = recovered;
        } catch { /* Preserve the displayed token for the user's explicit retry. */ }
        if (requestSequence.current !== sequence) return;
        if (confirmed?.status === "completed") {
          forgetOperation(current.asset.id);
          updateDialog(null);
          visuals.refresh();
        } else if (confirmed) {
          rememberOperation(confirmed);
          updateDialog({ ...current, result: confirmed, submitting: false, attempted: true, error: requestError });
        } else {
          updateDialog({ ...current, submitting: false, attempted: false, error: requestError });
        }
      }
    }
  }

  function openRetry(operation: VisualCleanupResult) {
    if (dialog || busy) return;
    const asset = visuals.assets.find((item) => item.id === operation.assetId) ?? { id: operation.assetId, name: operation.name };
    const selected = selectedAssetIds.has(operation.assetId);
    const initial: ImageCleanupDialog = { asset, preview: null, operationToken: operation.operationToken, result: operation,
      loadingPreview: selected, submitting: false, attempted: true, error: operation.error ?? resultMessage(operation) };
    const sequence = ++requestSequence.current;
    updateDialog(initial);
    if (selected) {
      void previewVisualAssetCleanup(operation.assetId).then((preview) => {
        if (requestSequence.current === sequence) updateDialog({ ...initial, preview, loadingPreview: false });
      }).catch((error: unknown) => {
        if (requestSequence.current === sequence) updateDialog({ ...initial, loadingPreview: false,
          error: error instanceof VisualApiError || error instanceof Error ? error.message : "The image reference check could not be loaded." });
      });
    }
  }

  function beginRename(asset: VisualAsset) {
    setEditingAssetId(asset.id);
    setRenameValue(asset.name);
    setRenameError("");
  }

  function cancelRename() {
    setEditingAssetId(null);
    setRenameValue("");
    setRenameError("");
  }

  async function saveRename(asset: VisualAsset) {
    const name = renameValue.trim();
    if (busy || renaming) return;
    if (!name || name.length > 160) {
      setRenameError("Enter an image name between 1 and 160 characters.");
      return;
    }
    if (name === asset.name) { cancelRename(); return; }
    setRenaming(true);
    setRenameError("");
    try {
      await renameVisualAsset(asset.id, name, asset.name);
      cancelRename();
      visuals.refresh();
    } catch (error: unknown) {
      setRenameError(error instanceof VisualApiError || error instanceof Error ? error.message : "The image name could not be updated.");
      if (error instanceof VisualApiError && error.status === 409) visuals.refresh();
    } finally {
      setRenaming(false);
    }
  }

  function closeDialog() {
    if (!dialog || dialog.submitting) return;
    const attempted = dialog.attempted;
    requestSequence.current += 1;
    updateDialog(null);
    if (attempted) {
      visuals.refresh();
      setReloadOperations((value) => value + 1);
    }
  }

  const retryMap = new Map(operations.map((item) => [item.assetId, item]));
  for (const item of Object.values(localOperations)) if (!retryMap.has(item.assetId)) retryMap.set(item.assetId, item);
  const retryOperations = [...retryMap.values()];

  return (
    <>
      <section className="visual-gallery" aria-labelledby="visual-gallery-title" inert={dialog !== null}>
        <div className="visual-gallery-heading">
          <div><h2 id="visual-gallery-title">Image library</h2>
            <p className="field-help">Manage reusable backgrounds and illustrations. Images used by a project or saved video history stay protected.</p></div>
          <button type="button" disabled={visuals.checking} onClick={() => {
            visuals.refresh();
            setReloadOperations((value) => value + 1);
          }}>Refresh gallery and cleanup status</button>
        </div>
        {busy && <p className="field-help" role="status">Image cleanup is disabled while local generation or cleanup work is active.</p>}
        {visuals.error && <p className="input-error" role="alert">{visuals.error}</p>}
        {operationsLoading && <p className="field-help" role="status">Checking for unfinished image cleanup…</p>}
        {operationsError && <p className="input-error" role="alert">{operationsError}</p>}
        {retryOperations.length > 0 && <section className="visual-cleanup-retries" aria-label="Image cleanup retries">
          <h3>Cleanup needing attention</h3>
          {retryOperations.map((operation) => {
            const selected = selectedAssetIds.has(operation.assetId);
            return <div className="visual-cleanup-retry" key={operation.assetId}>
              <span>{operation.name} · {operation.status} · {operation.failedFiles} failed</span>
              <button type="button" disabled={busy || !!dialog} onClick={() => openRetry(operation)}>Review cleanup</button>
              {selected && <span className="field-help">Selected in “{projectName}”. Review cleanup to check its current project references.</span>}
            </div>;
          })}
        </section>}
        {visuals.checking && <p className="field-help" role="status">Loading locally stored images…</p>}
        {!visuals.checking && !visuals.error && visuals.assets.length === 0 && <p className="field-help">The image library is empty.</p>}
        {!visuals.checking && !visuals.error && visuals.assets.length > 0 && <ul className="visual-gallery-list">
          {visuals.assets.map((asset) => {
            const selected = selectedAssetIds.has(asset.id);
            const pendingOperation = retryMap.get(asset.id);
            return <li key={asset.id}>
              {asset.available
                ? <img src={visualAssetUrl(asset.id)} alt="" loading="lazy" />
                : <span className="visual-gallery-placeholder" aria-hidden="true">Image unavailable</span>}
              <div className="visual-gallery-details">
                <strong>{asset.name}</strong>
                <span>{asset.kind === "background" ? "Background" : "Illustration"} · {asset.width} × {asset.height} · {formatResourceBytes(asset.sizeBytes)}</span>
                {!asset.available && <span className="input-error">Image source is unavailable.</span>}
                {selected && <span className="field-help">Selected in “{projectName}”. Preview cleanup to check other project references; deletion stays blocked while this project uses the image.</span>}
                {pendingOperation && <span className="field-help">Cleanup is {pendingOperation.status}. Review the same operation above.</span>}
              </div>
              <div className="visual-gallery-actions">
                {editingAssetId === asset.id ? <form className="visual-rename-form" onSubmit={(event) => { event.preventDefault(); void saveRename(asset); }}>
                  <label htmlFor={`visual-name-${asset.id}`}>Image name</label>
                  <input id={`visual-name-${asset.id}`} value={renameValue} maxLength={160} disabled={busy || renaming}
                    onChange={(event) => { setRenameValue(event.target.value); setRenameError(""); }} />
                  {renameError && <span className="input-error" role="alert">{renameError}</span>}
                  <div><button type="submit" disabled={busy || renaming}>{renaming ? "Saving…" : "Save name"}</button>
                    <button type="button" disabled={renaming} onClick={cancelRename}>Cancel</button></div>
                </form> : <button type="button" disabled={busy || !!pendingOperation || !!dialog}
                  onClick={() => beginRename(asset)}>Rename</button>}
                {pendingOperation
                  ? <button type="button" disabled={busy || !!dialog} onClick={() => openRetry(pendingOperation)}>Review cleanup</button>
                  : <button type="button" className="delete-button"
                    disabled={busy || visuals.checking || !!visuals.error || !!dialog}
                    onClick={() => { void startPreview(asset); }}>{selected ? "Preview cleanup…" : "Delete image…"}</button>}
              </div>
            </li>;
          })}
        </ul>}
      </section>

      {dialog && <div className="cleanup-backdrop">
        <section className="cleanup-dialog" role="alertdialog" aria-modal="true" aria-labelledby="visual-cleanup-title"
          aria-describedby="visual-cleanup-description" onKeyDown={(event) => {
            if (event.key === "Escape" && !dialog.submitting) closeDialog();
          }}>
          <h2 id="visual-cleanup-title" ref={dialogHeading} tabIndex={-1}>Delete “{dialog.asset.name}” from the image library?</h2>
          <p id="visual-cleanup-description">This removes the selected image and its library files only. Project and historical-video references are protected by the local service.</p>
          {dialog.asset.kind && <p className="field-help">Image type: {dialog.asset.kind === "background" ? "Background" : "Illustration"}
            {dialog.asset.width && dialog.asset.height ? ` · ${dialog.asset.width} × ${dialog.asset.height}` : ""}
            {dialog.asset.sizeBytes ? ` · ${formatResourceBytes(dialog.asset.sizeBytes)}` : ""}</p>}
          {selectedAssetIds.has(dialog.asset.id) && <p className="field-help" role="status">This image is selected in “{projectName}”. The local service will preserve it while the project uses it; confirm remains disabled until you change that selection.</p>}
          {dialog.loadingPreview && <p className="field-help" role="status">Calculating the image cleanup preview…</p>}
          {dialog.preview && <div className="cleanup-preview" aria-label="Image cleanup preview">
            <p><strong>Will delete</strong> · {dialog.preview.deleteFiles.count} files · {formatResourceBytes(dialog.preview.deleteFiles.bytes)}</p>
            {dialog.preview.warnings.map((warning, index) => <p className="cleanup-warning" key={`image-warning-${index}`}>{warning}</p>)}
          </div>}
          {dialog.result && <div className="cleanup-preview" role="status">
            <p><strong>Status</strong> · {dialog.result.status} · {dialog.result.deletedFiles} files removed · {dialog.result.failedFiles} failed</p>
            {dialog.result.error && <p className="input-error">{dialog.result.error}</p>}
            {dialog.result.warnings.map((warning, index) => <p className="cleanup-warning" key={`image-result-warning-${index}`}>{warning}</p>)}
          </div>}
          {dialog.error && <p className="input-error" role="alert">{dialog.error}</p>}
          <div className="confirmation-actions">
            <button type="button" disabled={dialog.submitting} onClick={closeDialog}>{dialog.attempted ? "Close and refresh" : "Cancel"}</button>
            {!dialog.attempted && <button type="button" disabled={dialog.loadingPreview || dialog.submitting} onClick={() => { void refreshPreview(); }}>Refresh preview</button>}
            <button type="button" className="delete-button" disabled={dialog.loadingPreview || dialog.submitting || !dialog.operationToken || selectedAssetIds.has(dialog.asset.id)}
              onClick={() => { void confirmCleanup(); }}>{dialog.attempted ? "Retry same cleanup" : "Confirm delete"}</button>
          </div>
        </section>
      </div>}
    </>
  );
}
