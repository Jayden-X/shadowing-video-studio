import { useEffect, useState, type ChangeEvent } from "react";
import type { SentenceId } from "./domain/sentences";
import { visualAssetUrl, VisualApiError, type VisualAsset, type VisualKind } from "./visualApi";
import type { useVisuals } from "./useVisuals";

type VisualLibraryState = ReturnType<typeof useVisuals>;
const UPLOAD_TIMEOUT_MS = 60_000;

function VisualAssetPicker({ id, label, kind, value, onChange, visuals, disabled }: {
  id: string;
  label: string;
  kind: VisualKind;
  value: string | null;
  onChange: (assetId: string | null) => void;
  visuals: VisualLibraryState;
  disabled: boolean;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [previewFailed, setPreviewFailed] = useState(false);
  const choices = visuals.assets.filter((asset) => asset.kind === kind);
  const selected: VisualAsset | undefined = choices.find((asset) => asset.id === value);

  useEffect(() => setPreviewFailed(false), [selected?.id]);

  async function uploadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setUploadError("");
    setUploading(true);
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, UPLOAD_TIMEOUT_MS);
    try {
      const uploaded = await visuals.upload(file, kind, controller.signal);
      onChange(uploaded.id);
    } catch (error: unknown) {
      setUploadError(timedOut
        ? "Image upload timed out. Refresh the image library before explicitly retrying; the upload may have been saved. Your current selection is preserved."
        : error instanceof VisualApiError ? error.message
        : "Image upload failed. Refresh the image library before explicitly retrying; the upload may have been saved. Your current selection is preserved.");
    } finally {
      clearTimeout(timeout);
      setUploading(false);
    }
  }

  const accepts = visuals.status?.formats.join(",") ?? "image/png,image/jpeg,image/webp";
  const libraryUnavailable = visuals.status !== null && !visuals.status.available;
  const disableUpload = disabled || uploading || visuals.checking || libraryUnavailable || !!visuals.error;
  return (
    <div className="visual-asset-picker">
      <label htmlFor={`${id}-asset`}>{label}</label>
      <select id={`${id}-asset`} value={value ?? ""} disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.target.value || null)}>
        <option value="">None</option>
        {value && !choices.some((asset) => asset.id === value) && (
          <option value={value}>Selected image is unavailable</option>
        )}
        {choices.map((asset) => (
          <option key={asset.id} value={asset.id} disabled={!asset.available}>
            {asset.name} · {asset.width} × {asset.height}{asset.available ? "" : " · Unavailable"}
          </option>
        ))}
      </select>
      <label className="upload-image-label" htmlFor={`${id}-upload`}>Upload a new image</label>
      <input id={`${id}-upload`} type="file" accept={accepts} disabled={disableUpload}
        aria-label={`Upload image for ${label}`} onChange={(event) => { void uploadFile(event); }} />
      {uploading && <p className="field-help" role="status">Uploading image… This can take up to one minute while the local service validates it.</p>}
      {uploadError && <p className="input-error" role="alert">{uploadError}</p>}
      {selected?.available && !previewFailed && (
        <figure className="visual-preview">
          <img src={visualAssetUrl(selected.id)} alt={`${selected.name} preview`} loading="lazy"
            onError={() => setPreviewFailed(true)} />
          <figcaption>{selected.name} · {selected.width} × {selected.height}</figcaption>
        </figure>
      )}
      {previewFailed && selected && <p className="input-error" role="alert">This image preview is unavailable. Refresh the library, then re-upload or select another image.</p>}
      {selected && !selected.available && <p className="input-error" role="status">
        {selected.reason ?? `${selected.name} is unavailable. Re-upload it or choose another image.`}
      </p>}
      {value && !selected && !visuals.checking && !visuals.error && (
        <p className="input-error" role="status">The selected image is not listed in the library. Refresh, then re-upload or select another image.</p>
      )}
    </div>
  );
}

export function BackgroundImageControls({ visuals, value, onChange, disabled }: {
  visuals: VisualLibraryState;
  value: string | null;
  onChange: (assetId: string | null) => void;
  disabled: boolean;
}) {
  return (
    <section className="visual-library" aria-labelledby="background-image-title">
      <div className="visual-library-heading">
        <div>
          <h3 id="background-image-title">Video background</h3>
          <p className="field-help">
            The selected image applies throughout the video. Light backgrounds keep the animated
            black frequency bars clear; sentence illustrations appear on the right.
          </p>
        </div>
        <button type="button" disabled={visuals.checking} onClick={visuals.refresh}>Refresh image library</button>
      </div>
      {visuals.checking && <p className="field-help" role="status">Loading locally stored images…</p>}
      {!visuals.checking && visuals.error && <p className="input-error" role="status">{visuals.error}</p>}
      {!visuals.checking && !visuals.error && visuals.status && !visuals.status.available && (
        <p className="input-error" role="status">{visuals.status.reason ?? "The local image library is unavailable. Refresh to retry."}</p>
      )}
      <VisualAssetPicker id="video-background" label="Background image" kind="background" value={value}
        onChange={onChange} visuals={visuals} disabled={disabled} />
    </section>
  );
}

export function SentenceIllustrationPicker({ visuals, sentenceId, position, value, onChange, disabled }: {
  visuals: VisualLibraryState;
  sentenceId: SentenceId;
  position: number;
  value: string | null;
  onChange: (assetId: string | null) => void;
  disabled: boolean;
}) {
  return (
    <section className="sentence-illustration" aria-labelledby={`illustration-title-${sentenceId}`}>
      <h4 id={`illustration-title-${sentenceId}`}>Right-side illustration</h4>
      <p className="field-help">Shown for sentence {position}, including its five-second practice pause.</p>
      <VisualAssetPicker id={`illustration-${sentenceId}`} label={`Illustration for sentence ${position}`} kind="illustration"
        value={value} onChange={onChange} visuals={visuals} disabled={disabled} />
    </section>
  );
}
