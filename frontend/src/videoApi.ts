import { speechInputProblem, type SpeechBinding } from "./domain/speech";

export type VideoSentence = { id: string; text: string; assetId: string; illustrationAssetId?: string | null };
export type VideoStatus = { available: boolean; reason: string | null };
export type VideoJob = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  completedSentences: number;
  totalSentences: number;
  assetId: string | null;
  durationSeconds: number | null;
  error: string | null;
};
export class VideoApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

const opaqueId = /^[a-f0-9]{32}$/;
const INVALID = "The local service returned invalid video progress. Your dialogue, speech, and prior exports are preserved.";
const UNAVAILABLE = "Video rendering is unavailable. Check the local service's workspace, FFmpeg, and font configuration.";
const FAILED = "Video rendering failed. Check the local renderer, then explicitly try again. Your speech and prior exports are preserved.";
const fingerprint = /^[a-f0-9]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}
function isSafeError(value: unknown): boolean {
  return value === null || (typeof value === "string" && value.length <= 500);
}
function responseError(status: number): VideoApiError {
  if (status === 404) return new VideoApiError("This video job or export is unavailable in this service session. After a service restart, generate speech and video again.", status);
  if (status === 422) return new VideoApiError("The selected voice or speech configuration is unsupported or stale. Refresh speech availability, choose a listed voice, explicitly generate its audio, then retry video.", status);
  if (status === 409) return new VideoApiError("The local service is busy or the audio no longer matches the selected speech settings. Wait for current work, refresh speech availability, explicitly regenerate affected audio, then retry video.", status);
  if (status === 400 || status === 413) return new VideoApiError("The video input is invalid. Ensure every current sentence has matching audio; split long sentences to fit the page before regenerating speech.", status);
  if (status === 429) return new VideoApiError("The local service session limit is reached. Restart the service after saving your work.", status);
  if (status === 503) return new VideoApiError(UNAVAILABLE);
  return new VideoApiError("The video request could not be confirmed. The local renderer may still be running; check its progress before retrying. Your speech and prior exports are preserved.");
}
async function requestJson(url: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try { response = await fetch(url, init); }
  catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for video.", "AbortError");
    throw responseError(0);
  }
  if (!response.ok) throw responseError(response.status);
  try { return await response.json(); }
  catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for video.", "AbortError");
    throw new VideoApiError(INVALID);
  }
}
export async function getVideoStatus(signal?: AbortSignal): Promise<VideoStatus> {
  const value = await requestJson("/api/video/status", { signal });
  if (!isRecord(value) || !exactKeys(value, ["available", "reason"]) || typeof value.available !== "boolean" || !isSafeError(value.reason)) throw new VideoApiError(INVALID);
  return { available: value.available, reason: value.available ? null : UNAVAILABLE };
}
function validateJob(value: unknown, total: number, expectedId?: string): VideoJob {
  if (!isRecord(value) || !exactKeys(value, ["id", "status", "completedSentences", "totalSentences", "assetId", "durationSeconds", "error"])
    || typeof value.id !== "string" || !opaqueId.test(value.id) || (expectedId !== undefined && value.id !== expectedId)
    || (value.status !== "queued" && value.status !== "running" && value.status !== "completed" && value.status !== "failed")
    || value.totalSentences !== total || typeof value.completedSentences !== "number" || !Number.isInteger(value.completedSentences)
    || value.completedSentences < 0 || value.completedSentences > total || !isSafeError(value.error)
    || (value.assetId !== null && (typeof value.assetId !== "string" || !opaqueId.test(value.assetId)))
    || (value.durationSeconds !== null && (typeof value.durationSeconds !== "number" || !Number.isFinite(value.durationSeconds) || value.durationSeconds <= 0))) throw new VideoApiError(INVALID);
  if (value.status === "completed") {
    if (value.completedSentences !== total || value.assetId === null || value.durationSeconds === null || value.error !== null) throw new VideoApiError(INVALID);
  } else {
    if (value.assetId !== null || value.durationSeconds !== null) throw new VideoApiError(INVALID);
    if (value.status === "failed" ? value.error === null : value.error !== null) throw new VideoApiError(INVALID);
  }
  return { id: value.id, status: value.status, completedSentences: value.completedSentences, totalSentences: total,
    assetId: value.assetId, durationSeconds: value.durationSeconds, error: value.error === null ? null : FAILED };
}
export async function createVideoJob(
  sentences: readonly VideoSentence[],
  binding: SpeechBinding,
  backgroundAssetId?: string | null,
  signal?: AbortSignal,
): Promise<VideoJob> {
  const problem = speechInputProblem(sentences);
  if (problem) throw new VideoApiError(problem);
  if (sentences.some((sentence) => !opaqueId.test(sentence.assetId))) {
    throw new VideoApiError("Every sentence needs current generated audio before rendering video.");
  }
  if (!binding.voice.trim() || !fingerprint.test(binding.configurationFingerprint)) {
    throw new VideoApiError("Choose a currently supported speech voice before rendering video.");
  }
  if (sentences.some((sentence) => sentence.illustrationAssetId != null && !opaqueId.test(sentence.illustrationAssetId))
    || (backgroundAssetId != null && !opaqueId.test(backgroundAssetId))) {
    throw new VideoApiError("Every selected image must have a valid local asset.");
  }
  return validateJob(await requestJson("/api/video/jobs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sentences: sentences.map(({ id, text, assetId, illustrationAssetId }) => ({
        id, text, assetId,
        ...(illustrationAssetId == null ? {} : { illustrationAssetId }),
      })),
      voice: binding.voice,
      configurationFingerprint: binding.configurationFingerprint,
      ...(backgroundAssetId == null ? {} : { backgroundAssetId }),
    }), signal,
  }), sentences.length);
}
export async function getVideoJob(id: string, total: number, signal?: AbortSignal): Promise<VideoJob> {
  if (!opaqueId.test(id)) throw new VideoApiError(INVALID);
  return validateJob(await requestJson(`/api/video/jobs/${id}`, { signal }), total, id);
}
export function videoAssetUrl(id: string, download = false): string {
  if (!opaqueId.test(id)) throw new VideoApiError("Invalid video asset identifier.");
  return `/api/video/assets/${id}${download ? "?download=true" : ""}`;
}
