import { isWellFormedText, type SentenceItem } from "./domain/sentences";
import { jobMatchesSnapshot, speechInputProblem, type SpeechBinding, type SpeechJob, type SpeechSentence } from "./domain/speech";
import type { ProjectSnapshot } from "./projectApi";

export type SpeechStatus = { available: boolean; reason: string | null; voice: string; model: string; backend: string };
export type SpeechVoice = { id: string; label: string; configurationFingerprint: string };
export type SpeechCapabilities = {
  available: boolean;
  reason: string | null;
  defaultVoice: string | null;
  model: string;
  language: "English";
  voices: SpeechVoice[];
};
export type ProjectSpeechJob = SpeechJob & {
  projectId: string;
  documentId: string;
  projectRevision: number;
  submissionToken: string;
};
export type ProjectSpeechCommand = {
  projectId: string;
  documentId: string;
  expectedRevision: number;
  name: string;
  snapshot: ProjectSnapshot;
  submissionToken: string;
  singleSentenceId?: string;
};
export class SpeechApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

const INVALID_RESPONSE = "The local service returned invalid speech progress. Your text and previously generated audio are preserved.";
const UNAVAILABLE = "Speech is unavailable. Check the local service's configured workspace, Qwen runtime, and local model.";
const GENERATION_FAILED = "Speech generation failed. Check the local runtime, then retry the affected sentence. Successful audio is preserved.";
const opaqueId = /^[a-f0-9]{32}$/;
const fingerprint = /^[a-f0-9]{64}$/;

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
  if (status === 409) return new SpeechApiError("The selected speech configuration may be stale, or a local job is still active. Refresh speech availability; after any job finishes, choose a currently listed voice and explicitly generate speech again.", status);
  if (status === 422) return new SpeechApiError("The selected voice or speech configuration is unsupported or stale. Refresh speech availability, choose a currently listed voice, then explicitly generate speech again.", status);
  if (status === 429) return new SpeechApiError("This session's speech media limit is reached. Restart the local service after saving your work.", status);
  if (status === 400 || status === 413) return new SpeechApiError("The sentence list is invalid or too large. Review its text before generating speech.", status);
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

export async function getSpeechCapabilities(signal?: AbortSignal): Promise<SpeechCapabilities> {
  const value = await requestJson("/api/speech/capabilities", { signal });
  if (!isRecord(value) || !hasExactKeys(value, ["available", "reason", "defaultVoice", "model", "language", "voices"])
    || typeof value.available !== "boolean" || !safeError(value.reason)
    || (value.defaultVoice !== null && (!boundedText(value.defaultVoice, 100) || !value.defaultVoice.trim()))
    || !boundedText(value.model, 200) || !value.model.trim() || value.language !== "English"
    || !Array.isArray(value.voices)) throw new SpeechApiError(INVALID_RESPONSE);
  const voices: SpeechVoice[] = [];
  const ids = new Set<string>();
  for (const voice of value.voices as unknown[]) {
    if (!isRecord(voice) || !hasExactKeys(voice, ["id", "label", "configurationFingerprint"])
      || !boundedText(voice.id, 100) || !voice.id.trim() || ids.has(voice.id)
      || !boundedText(voice.label, 120) || !voice.label.trim()
      || typeof voice.configurationFingerprint !== "string" || !fingerprint.test(voice.configurationFingerprint)) {
      throw new SpeechApiError(INVALID_RESPONSE);
    }
    ids.add(voice.id);
    voices.push({ id: voice.id, label: voice.label, configurationFingerprint: voice.configurationFingerprint });
  }
  if (value.defaultVoice !== null && !ids.has(value.defaultVoice)) throw new SpeechApiError(INVALID_RESPONSE);
  return { available: value.available, reason: value.reason as string | null, defaultVoice: value.defaultVoice as string | null,
    model: value.model, language: "English", voices };
}

function validateJob(value: unknown, snapshot: readonly SentenceItem[], binding: SpeechBinding, expectedId?: string,
  projectCommand?: ProjectSpeechCommand): SpeechJob | ProjectSpeechJob {
  const invalid = () => new SpeechApiError(INVALID_RESPONSE);
  const expectedKeys = projectCommand
    ? ["id", "status", "sentences", "error", "voice", "configurationFingerprint", "projectId", "documentId", "projectRevision", "submissionToken"]
    : ["id", "status", "sentences", "error", "voice", "configurationFingerprint"];
  if (!isRecord(value) || !hasExactKeys(value, expectedKeys)
    || typeof value.id !== "string" || !opaqueId.test(value.id) || (expectedId !== undefined && value.id !== expectedId)
    || value.voice !== binding.voice || value.configurationFingerprint !== binding.configurationFingerprint
    || (value.status !== "queued" && value.status !== "running" && value.status !== "completed" && value.status !== "failed")
    || !safeError(value.error) || !Array.isArray(value.sentences) || value.sentences.length !== snapshot.length) throw invalid();
  const sentences: SpeechSentence[] = [];
  for (const item of value.sentences as unknown[]) {
    if (!isRecord(item) || !hasExactKeys(item, ["id", "text", "status", "assetId", "durationSeconds", "error", "reused", "voice", "configurationFingerprint"])
      || !boundedText(item.id, 100) || !boundedText(item.text, 4_000)
      || item.voice !== binding.voice || item.configurationFingerprint !== binding.configurationFingerprint
      || (item.status !== "pending" && item.status !== "generating" && item.status !== "ready" && item.status !== "failed")
      || (item.assetId !== null && (typeof item.assetId !== "string" || !opaqueId.test(item.assetId)))
      || (item.durationSeconds !== null && (typeof item.durationSeconds !== "number" || !Number.isFinite(item.durationSeconds) || item.durationSeconds <= 0))
      || !safeError(item.error) || typeof item.reused !== "boolean") throw invalid();
    if (item.status === "ready") {
      if (item.assetId === null || item.durationSeconds === null || item.error !== null) throw invalid();
    } else if (item.assetId !== null || item.durationSeconds !== null || item.reused) throw invalid();
    if (item.status === "failed" && item.error === null) throw invalid();
    if ((item.status === "pending" || item.status === "generating") && item.error !== null) throw invalid();
    sentences.push({ id: item.id, text: item.text, voice: binding.voice, configurationFingerprint: binding.configurationFingerprint,
      status: item.status, assetId: item.assetId,
      durationSeconds: item.durationSeconds, error: item.error === null ? null : GENERATION_FAILED, reused: item.reused });
  }
  const job: SpeechJob = { id: value.id, status: value.status, voice: binding.voice,
    configurationFingerprint: binding.configurationFingerprint, sentences, error: value.error === null ? null : GENERATION_FAILED };
  if (!jobMatchesSnapshot(job, snapshot, binding)) throw invalid();
  if (job.status === "completed" && (job.error !== null || sentences.some((item) => item.status !== "ready"))) throw invalid();
  if (job.status === "failed" && (job.error === null || sentences.some((item) => item.status === "pending" || item.status === "generating"))) throw invalid();
  if (projectCommand) {
    if (value.projectId !== projectCommand.projectId || value.documentId !== projectCommand.documentId
      || !Number.isSafeInteger(value.projectRevision) || (value.projectRevision as number) < projectCommand.expectedRevision
      || value.submissionToken !== projectCommand.submissionToken) throw invalid();
    return { ...job, projectId: projectCommand.projectId, documentId: projectCommand.documentId,
      projectRevision: value.projectRevision as number, submissionToken: projectCommand.submissionToken };
  }
  return job;
}

export async function createSpeechJob(
  sentences: readonly SentenceItem[],
  force: boolean,
  binding: SpeechBinding,
  signal?: AbortSignal,
): Promise<SpeechJob> {
  const problem = speechInputProblem(sentences);
  if (problem) throw new SpeechApiError(problem);
  if (force && sentences.length !== 1) throw new SpeechApiError("Regenerate one sentence at a time.");
  if (!binding.voice.trim() || !fingerprint.test(binding.configurationFingerprint)) throw new SpeechApiError("Choose a currently supported speech voice before generating.");
  const value = await requestJson("/api/speech/jobs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sentences: sentences.map(({ id, text }) => ({ id, text })), force,
      voice: binding.voice, configurationFingerprint: binding.configurationFingerprint }), signal,
  });
  return validateJob(value, sentences, binding);
}

export async function createProjectSpeechJob(
  sentences: readonly SentenceItem[],
  binding: SpeechBinding,
  command: ProjectSpeechCommand,
  signal?: AbortSignal,
): Promise<ProjectSpeechJob> {
  const problem = speechInputProblem(sentences);
  if (problem) throw new SpeechApiError(problem);
  if (!binding.voice.trim() || !fingerprint.test(binding.configurationFingerprint)) throw new SpeechApiError("Choose a currently supported speech voice before generating.");
  if (command.singleSentenceId !== undefined && (sentences.length !== 1 || sentences[0].id !== command.singleSentenceId)) {
    throw new SpeechApiError("A single-sentence regeneration must match the selected sentence.");
  }
  const value = await requestJson(`/api/projects/${command.projectId}/speech`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      operationToken: command.submissionToken,
      expectedRevision: command.expectedRevision,
      name: command.name,
      snapshot: command.snapshot,
      configurationFingerprint: binding.configurationFingerprint,
      ...(command.singleSentenceId === undefined ? {} : { singleSentenceId: command.singleSentenceId }),
    }), signal,
  });
  return validateJob(value, sentences, binding, undefined, command) as ProjectSpeechJob;
}

export function validateProjectSpeechAttemptJob(value: unknown, snapshot: readonly SentenceItem[], binding: SpeechBinding): SpeechJob {
  return validateJob(value, snapshot, binding) as SpeechJob;
}
export async function getSpeechJob(
  id: string,
  snapshot: readonly SentenceItem[],
  binding: SpeechBinding,
  signal?: AbortSignal,
): Promise<SpeechJob> {
  if (!opaqueId.test(id)) throw new SpeechApiError(INVALID_RESPONSE);
  return validateJob(await requestJson(`/api/speech/jobs/${id}`, { signal }), snapshot, binding, id);
}
export function speechAssetUrl(id: string): string {
  if (!opaqueId.test(id)) throw new SpeechApiError("Invalid speech asset identifier.");
  return `/api/speech/assets/${id}`;
}
