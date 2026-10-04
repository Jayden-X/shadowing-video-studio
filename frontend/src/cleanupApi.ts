import { isWellFormedText } from "./domain/sentences";
import { parseProjectHistoryEntry, type ProjectHistoryEntry, type ProjectRecord } from "./projectApi";

const opaqueId = /^[a-f0-9]{32}$/;
const sentenceId = /^sentence-\d+$/;

export type ProjectCleanupMode = "project_only" | "intermediate" | "all";
export type CleanupFileSummary = { count: number; bytes: number };
export type ProjectCleanupPreview = {
  projectId: string;
  projectName: string;
  mode: ProjectCleanupMode;
  revision: number;
  planToken: string;
  deleteFiles: CleanupFileSummary;
  retainFiles: CleanupFileSummary;
  warnings: string[];
};
export type ProjectCleanupResult = {
  projectId: string;
  projectName: string;
  mode: ProjectCleanupMode;
  operationToken: string;
  status: "completed" | "partial" | "pending";
  deletedFiles: number;
  failedFiles: number;
  warnings: string[];
  error?: string | null;
};
export type RetainedAudioResource = {
  id: string;
  sentenceId: string;
  text: string;
  voice: string;
  durationSeconds: number;
  sizeBytes: number;
  available: boolean;
  reason?: string | null;
};
export type RetainedProjectResources = {
  projectId: string;
  projectName: string;
  mode: ProjectCleanupMode;
  deletedAt: string;
  cleanup: ProjectCleanupResult;
  audio: RetainedAudioResource[];
  videos: ProjectHistoryEntry[];
};

export class CleanupApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

const INVALID = "The local service returned invalid project cleanup data.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}
function boundedText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length <= max && isWellFormedText(value);
}
function safeReason(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || boundedText(value, 500);
}
function isCleanupMode(value: unknown): value is ProjectCleanupMode {
  return value === "project_only" || value === "intermediate" || value === "all";
}
function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 80 && Number.isFinite(Date.parse(value));
}
function parseFileSummary(value: unknown): CleanupFileSummary | null {
  if (!isRecord(value) || !exactKeys(value, ["count", "bytes"])
    || !Number.isSafeInteger(value.count) || (value.count as number) < 0
    || !Number.isSafeInteger(value.bytes) || (value.bytes as number) < 0) return null;
  return { count: value.count as number, bytes: value.bytes as number };
}
function parseWarnings(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > 100 || !value.every((item) => boundedText(item, 500))) return null;
  return [...value] as string[];
}
function parseProjectIdentity(value: Record<string, unknown>): { projectId: string; projectName: string; mode: ProjectCleanupMode } | null {
  if (typeof value.projectId !== "string" || !opaqueId.test(value.projectId)
    || typeof value.projectName !== "string" || !value.projectName.trim() || !boundedText(value.projectName, 120)
    || !isCleanupMode(value.mode)) return null;
  return { projectId: value.projectId, projectName: value.projectName, mode: value.mode };
}
function parsePreview(value: unknown): ProjectCleanupPreview | null {
  if (!isRecord(value)) return null;
  const identity = parseProjectIdentity(value);
  const deleteFiles = parseFileSummary(value.deleteFiles);
  const retainFiles = parseFileSummary(value.retainFiles);
  const warnings = parseWarnings(value.warnings);
  if (!identity || !Number.isSafeInteger(value.revision) || (value.revision as number) < 0
    || typeof value.planToken !== "string" || !opaqueId.test(value.planToken)
    || !deleteFiles || !retainFiles || !warnings) return null;
  return { ...identity, revision: value.revision as number, planToken: value.planToken, deleteFiles, retainFiles, warnings };
}
function parseCleanupResult(value: unknown): ProjectCleanupResult | null {
  if (!isRecord(value) || !exactKeys(value, ["projectId", "projectName", "mode", "operationToken", "status", "deletedFiles", "failedFiles", "warnings"])
    && !exactKeys(value, ["projectId", "projectName", "mode", "operationToken", "status", "deletedFiles", "failedFiles", "warnings", "error"])) return null;
  const identity = parseProjectIdentity(value);
  const warnings = parseWarnings(value.warnings);
  if (!identity || typeof value.operationToken !== "string" || !opaqueId.test(value.operationToken)
    || (value.status !== "completed" && value.status !== "partial" && value.status !== "pending")
    || !Number.isSafeInteger(value.deletedFiles) || (value.deletedFiles as number) < 0
    || !Number.isSafeInteger(value.failedFiles) || (value.failedFiles as number) < 0
    || !warnings || !safeReason(value.error)) return null;
  return { ...identity, operationToken: value.operationToken, status: value.status,
    deletedFiles: value.deletedFiles as number, failedFiles: value.failedFiles as number, warnings,
    ...(Object.hasOwn(value, "error") ? { error: value.error as string | null } : {}) };
}
function parseRetainedAudio(value: unknown): RetainedAudioResource | null {
  if (!isRecord(value) || !exactKeys(value, ["id", "sentenceId", "text", "voice", "durationSeconds", "sizeBytes", "available"])
    && !exactKeys(value, ["id", "sentenceId", "text", "voice", "durationSeconds", "sizeBytes", "available", "reason"])) return null;
  if (typeof value.id !== "string" || !opaqueId.test(value.id)
    || typeof value.sentenceId !== "string" || !sentenceId.test(value.sentenceId)
    || !boundedText(value.text, 4000) || typeof value.voice !== "string" || !value.voice.trim() || !boundedText(value.voice, 100)
    || typeof value.durationSeconds !== "number" || !Number.isFinite(value.durationSeconds) || value.durationSeconds <= 0
    || !Number.isSafeInteger(value.sizeBytes) || (value.sizeBytes as number) < 0 || typeof value.available !== "boolean"
    || !safeReason(value.reason)) return null;
  return { id: value.id, sentenceId: value.sentenceId, text: value.text, voice: value.voice,
    durationSeconds: value.durationSeconds, sizeBytes: value.sizeBytes as number, available: value.available,
    ...(Object.hasOwn(value, "reason") ? { reason: value.reason as string | null } : {}) };
}
function parseRetainedProject(value: unknown): RetainedProjectResources | null {
  if (!isRecord(value) || !exactKeys(value, ["projectId", "projectName", "mode", "deletedAt", "cleanup", "audio", "videos"])) return null;
  const identity = parseProjectIdentity(value);
  const cleanup = parseCleanupResult(value.cleanup);
  if (!identity || !isTimestamp(value.deletedAt) || !cleanup || cleanup.projectId !== identity.projectId
    || cleanup.projectName !== identity.projectName || cleanup.mode !== identity.mode
    || !Array.isArray(value.audio) || !Array.isArray(value.videos)) return null;
  const audio = value.audio.map(parseRetainedAudio);
  const videos = value.videos.map(parseProjectHistoryEntry);
  if (audio.some((item) => item === null) || videos.some((item) => item === null)
    || (videos as ProjectHistoryEntry[]).some((item) => item.projectId !== identity.projectId)) return null;
  return { ...identity, deletedAt: value.deletedAt, cleanup, audio: audio as RetainedAudioResource[], videos: videos as ProjectHistoryEntry[] };
}

async function requestJson(url: string, init: RequestInit = {}): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for retained project resources.", "AbortError");
    throw new CleanupApiError("The local service could not confirm project cleanup. Retry the same cleanup operation to check its result.");
  }
  if (!response.ok) {
    if (response.status === 404) throw new CleanupApiError("This project or its cleanup operation is no longer available. Refresh the saved project list and retained resources.", 404);
    if (response.status === 409) throw new CleanupApiError("The project changed or local work is still active. Refresh the project, wait for work to finish, then preview cleanup again.", 409);
    if (response.status === 400 || response.status === 422) throw new CleanupApiError("The cleanup request is invalid. Preview the current project again before retrying.", response.status);
    if (response.status === 429) throw new CleanupApiError("The local service is busy. Wait for current work to finish, then retry cleanup.", response.status);
    throw new CleanupApiError("The local service could not complete project cleanup. Retry the same cleanup operation to check its result.", response.status);
  }
  try {
    return await response.json();
  } catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for retained project resources.", "AbortError");
    throw new CleanupApiError(INVALID);
  }
}

export async function previewProjectCleanup(project: ProjectRecord, mode: ProjectCleanupMode): Promise<ProjectCleanupPreview> {
  const value = await requestJson(`/api/projects/${project.id}/cleanup/preview`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, expectedRevision: project.revision }),
  });
  const preview = parsePreview(value);
  if (!preview || preview.projectId !== project.id || preview.projectName !== project.name
    || preview.mode !== mode || preview.revision !== project.revision) throw new CleanupApiError(INVALID);
  return preview;
}

export async function executeProjectCleanup(projectId: string, planToken: string): Promise<ProjectCleanupResult> {
  if (!opaqueId.test(projectId) || !opaqueId.test(planToken)) throw new CleanupApiError("Invalid project cleanup token.");
  const value = await requestJson(`/api/projects/${projectId}/cleanup`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ planToken }),
  });
  const result = parseCleanupResult(value);
  if (!result || result.projectId !== projectId || result.operationToken !== planToken) throw new CleanupApiError(INVALID);
  return result;
}

export async function getProjectCleanupResult(projectId: string, planToken: string): Promise<ProjectCleanupResult> {
  if (!opaqueId.test(projectId) || !opaqueId.test(planToken)) throw new CleanupApiError("Invalid project cleanup token.");
  const value = await requestJson(`/api/projects/${projectId}/cleanup/${planToken}`);
  const result = parseCleanupResult(value);
  if (!result || result.projectId !== projectId || result.operationToken !== planToken) throw new CleanupApiError(INVALID);
  return result;
}

export async function getRetainedProjectResources(signal?: AbortSignal): Promise<RetainedProjectResources[]> {
  const value = await requestJson("/api/projects/retained/resources", { signal });
  if (!isRecord(value) || !exactKeys(value, ["projects"]) || !Array.isArray(value.projects)) throw new CleanupApiError(INVALID);
  const projects = value.projects.map(parseRetainedProject);
  if (projects.some((item) => item === null) || new Set((projects as RetainedProjectResources[]).map((item) => item.projectId)).size !== projects.length) {
    throw new CleanupApiError(INVALID);
  }
  return projects as RetainedProjectResources[];
}

export function formatResourceBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let size = bytes;
  let unit = -1;
  do { size /= 1024; unit += 1; } while (size >= 1024 && unit < units.length - 1);
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`;
}
