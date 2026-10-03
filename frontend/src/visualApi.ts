import { isWellFormedText } from "./domain/sentences";

export type VisualKind = "background" | "illustration";
export type VisualMimeType = "image/png" | "image/jpeg" | "image/webp";
export type VisualStatus = {
  available: boolean;
  reason: string | null;
  maxUploadBytes: number;
  formats: VisualMimeType[];
};
export type VisualAsset = {
  id: string;
  kind: VisualKind;
  name: string;
  mimeType: VisualMimeType;
  width: number;
  height: number;
  sizeBytes: number;
  available: boolean;
  reason: string | null;
};

export class VisualApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

const opaqueId = /^[a-f0-9]{32}$/;
const supportedFormats: readonly VisualMimeType[] = ["image/png", "image/jpeg", "image/webp"];
const INVALID_RESPONSE = "The local service returned invalid image library data. Your selections are preserved.";
const UPLOAD_UNCONFIRMED = "The upload result could not be confirmed. Refresh the image library before explicitly retrying; the upload may have been saved. Your current selection is preserved.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}
function isSafeText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length <= max && isWellFormedText(value);
}
function isSafeReason(value: unknown): value is string | null {
  return value === null || isSafeText(value, 500);
}
function isVisualKind(value: unknown): value is VisualKind {
  return value === "background" || value === "illustration";
}
function isVisualMimeType(value: unknown): value is VisualMimeType {
  return typeof value === "string" && supportedFormats.includes(value as VisualMimeType);
}
function responseError(status: number, uploadRequest: boolean): VisualApiError {
  if (status === 400 || status === 415 || status === 422) {
    return new VisualApiError("Choose a valid PNG, JPEG, or WebP image within the image library's size and dimension limits.", status);
  }
  if (status === 404) return new VisualApiError("This image is no longer available. Refresh the image library, then re-upload or choose another image.", status);
  if (status === 413) return new VisualApiError("This image exceeds the 10 MiB upload limit.", status);
  if (status === 409 || status === 429) {
    return new VisualApiError(uploadRequest
      ? "The image library is busy. Wait for local media work to finish, then refresh the library before explicitly retrying the upload."
      : "The image library is busy. Wait for local media work to finish, then refresh to retry.", status);
  }
  if (status === 503) return new VisualApiError(uploadRequest
    ? "Image upload is unavailable in the local service. Existing library images may still be browsed; refresh to retry."
    : "The local image library is unavailable. Check the local service, then refresh to retry.", status);
  return new VisualApiError(uploadRequest
    ? "The upload result could not be confirmed. Refresh the image library before explicitly retrying; the upload may have been saved. Your current selection is preserved."
    : "The image library request failed. Refresh to retry; current selections are preserved.", status);
}

async function requestJson(url: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for the image library.", "AbortError");
    throw new VisualApiError(init.method === "POST"
      ? "The upload result could not be confirmed. Refresh the image library before explicitly retrying; the upload may have been saved. Your current selection is preserved."
      : "The local image library could not be reached. Refresh to retry; current selections are preserved.");
  }
  if (!response.ok) throw responseError(response.status, init.method === "POST");
  try {
    return await response.json();
  } catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for the image library.", "AbortError");
    throw new VisualApiError(init.method === "POST" ? UPLOAD_UNCONFIRMED : INVALID_RESPONSE);
  }
}

export async function getVisualStatus(signal?: AbortSignal): Promise<VisualStatus> {
  const value = await requestJson("/api/visuals/status", { signal });
  if (!isRecord(value) || !hasExactKeys(value, ["available", "reason", "maxUploadBytes", "formats"])
    || typeof value.available !== "boolean" || !isSafeReason(value.reason)
    || !Number.isSafeInteger(value.maxUploadBytes) || (value.maxUploadBytes as number) <= 0
    || !Array.isArray(value.formats) || value.formats.length === 0
    || !value.formats.every(isVisualMimeType) || new Set(value.formats).size !== value.formats.length) {
    throw new VisualApiError(INVALID_RESPONSE);
  }
  return {
    available: value.available,
    reason: value.available ? null : value.reason,
    maxUploadBytes: value.maxUploadBytes as number,
    formats: [...value.formats] as VisualMimeType[],
  };
}

function parseVisualAsset(value: unknown): VisualAsset | null {
  if (!isRecord(value) || !hasExactKeys(value, ["id", "kind", "name", "mimeType", "width", "height", "sizeBytes", "available", "reason"])
    || typeof value.id !== "string" || !opaqueId.test(value.id) || !isVisualKind(value.kind)
    || !isSafeText(value.name, 255) || !value.name.trim() || !isVisualMimeType(value.mimeType)
    || !Number.isSafeInteger(value.width) || (value.width as number) < 1 || (value.width as number) > 8192
    || !Number.isSafeInteger(value.height) || (value.height as number) < 1 || (value.height as number) > 8192
    || (value.width as number) * (value.height as number) > 20_000_000
    || !Number.isSafeInteger(value.sizeBytes) || (value.sizeBytes as number) < 1 || (value.sizeBytes as number) > 10 * 1024 * 1024
    || typeof value.available !== "boolean" || !isSafeReason(value.reason)) return null;
  return {
    id: value.id,
    kind: value.kind,
    name: value.name,
    mimeType: value.mimeType,
    width: value.width as number,
    height: value.height as number,
    sizeBytes: value.sizeBytes as number,
    available: value.available,
    reason: value.reason,
  };
}

export async function getVisualAssets(signal?: AbortSignal): Promise<VisualAsset[]> {
  const value = await requestJson("/api/visuals/assets", { signal });
  if (!isRecord(value) || !hasExactKeys(value, ["assets"]) || !Array.isArray(value.assets)) {
    throw new VisualApiError(INVALID_RESPONSE);
  }
  const assets = value.assets.map(parseVisualAsset);
  if (assets.some((asset) => asset === null) || new Set(assets.map((asset) => asset!.id)).size !== assets.length) {
    throw new VisualApiError(INVALID_RESPONSE);
  }
  return assets as VisualAsset[];
}

export async function uploadVisualAsset(file: File, kind: VisualKind, signal?: AbortSignal): Promise<VisualAsset> {
  if (file.size < 1 || file.size > 10 * 1024 * 1024) throw new VisualApiError("Choose an image no larger than 10 MiB.");
  if (file.name.length > 255 || !file.name.trim() || !isWellFormedText(file.name)) {
    throw new VisualApiError("Choose an image with a valid filename.");
  }
  const query = `kind=${kind}&name=${encodeURIComponent(file.name)}`;
  const value = await requestJson(`/api/visuals/assets?${query}`, {
    method: "POST",
    headers: { "Content-Type": file.type },
    body: file,
    signal,
  });
  const asset = parseVisualAsset(value);
  if (!asset || asset.kind !== kind || asset.name !== file.name || asset.sizeBytes !== file.size) {
    throw new VisualApiError(UPLOAD_UNCONFIRMED);
  }
  return asset;
}

export function visualAssetUrl(id: string): string {
  if (!opaqueId.test(id)) throw new VisualApiError("Invalid image identifier.");
  return `/api/visuals/assets/${id}`;
}
