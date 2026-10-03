import { isWellFormedText, type SentenceItem } from "./domain/sentences";
import { jobMatchesSnapshot, speechInputProblem, type SpeechJob, type SpeechSentence } from "./domain/speech";

export type SpeechStatus = { available: boolean; reason: string | null; voice: string; model: string; backend: string };
export class SpeechApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

const INVALID_RESPONSE = "The local service returned invalid speech progress. Your text and previously generated audio are preserved.";
const UNAVAILABLE = "Speech is unavailable. Check the local service's configured workspace, Qwen runtime, and local model.";
const GENERATION_FAILED = "Speech generation failed. Check the local runtime, then retry the affected sentence. Successful audio is preserved.";
const opaqueId = /^[a-f0-9]{32}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}
function boundedText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length <= max && isWellFormedText(value);
}
function safeError(value: unknown): boolean {
  return value === null || boundedText(value, 500);
}
function responseError(status: number): SpeechApiError {
  if (status === 409 || status === 429) return new SpeechApiError("The local service is busy or this session's media limit is reached. Wait for its current job, or restart the service after saving your work.");
  if (status === 400 || status === 413 || status === 422) return new SpeechApiError("The sentence list is invalid or too large. Review its text before generating speech.");
  if (status === 404) return new SpeechApiError("This speech job or audio is no longer available. After a service restart, generate speech again.", status);
  if (status === 503) return new SpeechApiError(UNAVAILABLE);
  return new SpeechApiError("The speech request could not be confirmed. The service may still be generating audio; check its progress before retrying. Your text and existing audio are preserved.");
}
async function requestJson(url: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try { response = await fetch(url, init); }
  catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for speech.", "AbortError");
    throw responseError(0);
  }
  if (!response.ok) throw responseError(response.status);
  try { return await response.json(); }
  catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for speech.", "AbortError");
    throw new SpeechApiError(INVALID_RESPONSE);
  }
}

export async function getSpeechStatus(signal?: AbortSignal): Promise<SpeechStatus> {
  const value = await requestJson("/api/speech/status", { signal });
  if (!isRecord(value) || !hasExactKeys(value, ["available", "reason", "voice", "model", "backend"])
    || typeof value.available !== "boolean" || !safeError(value.reason)
    || !boundedText(value.voice, 100) || !value.voice.trim()
    || !boundedText(value.model, 200) || !value.model.trim()
    || !boundedText(value.backend, 100) || !value.backend.trim()) throw new SpeechApiError(INVALID_RESPONSE);
  return { available: value.available, reason: value.available ? null : UNAVAILABLE, voice: value.voice, model: value.model, backend: value.backend };
}

function validateJob(value: unknown, snapshot: readonly SentenceItem[], expectedId?: string): SpeechJob {
  const invalid = () => new SpeechApiError(INVALID_RESPONSE);
  if (!isRecord(value) || !hasExactKeys(value, ["id", "status", "sentences", "error"])
    || typeof value.id !== "string" || !opaqueId.test(value.id) || (expectedId !== undefined && value.id !== expectedId)
    || (value.status !== "queued" && value.status !== "running" && value.status !== "completed" && value.status !== "failed")
    || !safeError(value.error) || !Array.isArray(value.sentences) || value.sentences.length !== snapshot.length) throw invalid();
  const sentences: SpeechSentence[] = [];
  for (const item of value.sentences as unknown[]) {
    if (!isRecord(item) || !hasExactKeys(item, ["id", "text", "status", "assetId", "durationSeconds", "error", "reused"])
      || !boundedText(item.id, 100) || !boundedText(item.text, 4_000)
      || (item.status !== "pending" && item.status !== "generating" && item.status !== "ready" && item.status !== "failed")
      || (item.assetId !== null && (typeof item.assetId !== "string" || !opaqueId.test(item.assetId)))
      || (item.durationSeconds !== null && (typeof item.durationSeconds !== "number" || !Number.isFinite(item.durationSeconds) || item.durationSeconds <= 0))
      || !safeError(item.error) || typeof item.reused !== "boolean") throw invalid();
    if (item.status === "ready") {
      if (item.assetId === null || item.durationSeconds === null || item.error !== null) throw invalid();
    } else if (item.assetId !== null || item.durationSeconds !== null || item.reused) throw invalid();
    if (item.status === "failed" && item.error === null) throw invalid();
    if ((item.status === "pending" || item.status === "generating") && item.error !== null) throw invalid();
    sentences.push({ id: item.id, text: item.text, status: item.status, assetId: item.assetId,
      durationSeconds: item.durationSeconds, error: item.error === null ? null : GENERATION_FAILED, reused: item.reused });
  }
  const job: SpeechJob = { id: value.id, status: value.status, sentences, error: value.error === null ? null : GENERATION_FAILED };
  if (!jobMatchesSnapshot(job, snapshot)) throw invalid();
  if (job.status === "completed" && (job.error !== null || sentences.some((item) => item.status !== "ready"))) throw invalid();
  if (job.status === "failed" && (job.error === null || sentences.some((item) => item.status === "pending" || item.status === "generating"))) throw invalid();
  return job;
}

export async function createSpeechJob(sentences: readonly SentenceItem[], force: boolean, signal?: AbortSignal): Promise<SpeechJob> {
  const problem = speechInputProblem(sentences);
  if (problem) throw new SpeechApiError(problem);
  if (force && sentences.length !== 1) throw new SpeechApiError("Regenerate one sentence at a time.");
  const value = await requestJson("/api/speech/jobs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sentences: sentences.map(({ id, text }) => ({ id, text })), force }), signal,
  });
  return validateJob(value, sentences);
}
export async function getSpeechJob(id: string, snapshot: readonly SentenceItem[], signal?: AbortSignal): Promise<SpeechJob> {
  if (!opaqueId.test(id)) throw new SpeechApiError(INVALID_RESPONSE);
  return validateJob(await requestJson(`/api/speech/jobs/${id}`, { signal }), snapshot, id);
}
export function speechAssetUrl(id: string): string {
  if (!opaqueId.test(id)) throw new SpeechApiError("Invalid speech asset identifier.");
  return `/api/speech/assets/${id}`;
}
