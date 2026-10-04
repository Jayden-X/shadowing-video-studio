import type { SentenceDocument, SentenceId } from "./domain/sentences";
import { isWellFormedText } from "./domain/sentences";

const opaqueId = /^[a-f0-9]{32}$/;
const sentenceIdPattern = /^sentence-\d+$/;

export type ProjectPreparationMode = "manual" | "ai";
export type ProjectSnapshot = {
  version: 1;
  documentId: string;
  sourceDraft: string;
  document: SentenceDocument;
  hasPrepared: boolean;
  mode: ProjectPreparationMode;
  voice: string;
  backgroundAssetId: string | null;
  illustrationsBySentence: Record<SentenceId, string>;
};

export type ProjectSummary = {
  id: string;
  name: string;
  revision: number;
  createdAt: string;
  updatedAt: string;
};

export type ProjectAudio = {
  id: string;
  text: string;
  voice: string;
  configurationFingerprint: string;
  assetId: string;
  durationSeconds: number;
  status: "ready";
  reused?: boolean;
};

export type ProjectHistoryEntry = {
  id: string;
  jobId: string;
  projectId: string;
  createdAt: string;
  durationSeconds: number | null;
  sizeBytes: number | null;
  available: boolean;
  reason?: string | null;
  snapshot: { editor: ProjectSnapshot; request: Record<string, unknown>; media?: Record<string, unknown> } | null;
};

export type ProjectAttempt = {
  id: string;
  projectId: string;
  documentId: string;
  kind: "speech" | "video";
  status: string;
  job: unknown;
  submissionToken: string;
  revision: number;
  snapshot: unknown;
  createdAt: string;
  updatedAt: string;
};

export type ProjectRecord = ProjectSummary & {
  snapshot: ProjectSnapshot;
};

export type ProjectSubmissionContext = {
  projectId: string;
  projectName: string;
  documentId: string;
  revision: number;
  name: string;
  snapshot: ProjectSnapshot;
  submissionToken: string;
  onAccepted?: (revision: number) => void;
  onFinished?: () => void;
};

export type ProjectDetail = ProjectRecord & {
  audio: ProjectAudio[];
  warnings: string[];
  history: ProjectHistoryEntry[];
  attempts: ProjectAttempt[];
};

export class ProjectApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => Object.hasOwn(value, key));
}

function validOpaqueId(value: unknown): value is string {
  return typeof value === "string" && opaqueId.test(value);
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 80 && Number.isFinite(Date.parse(value));
}

function parseSnapshot(value: unknown): ProjectSnapshot | null {
  if (!isRecord(value) || value.version !== 1 || !validOpaqueId(value.documentId)
    || typeof value.sourceDraft !== "string" || !isWellFormedText(value.sourceDraft)
    || !isRecord(value.document) || typeof value.document.sourceText !== "string"
    || !isWellFormedText(value.document.sourceText) || !Array.isArray(value.document.sentences)
    || !Number.isSafeInteger(value.document.nextSequence) || (value.document.nextSequence as number) < 1
    || typeof value.hasPrepared !== "boolean" || (value.mode !== "manual" && value.mode !== "ai")
    || typeof value.voice !== "string" || value.voice.length > 100 || !isWellFormedText(value.voice)
    || (value.backgroundAssetId !== null && !validOpaqueId(value.backgroundAssetId))
    || !isRecord(value.illustrationsBySentence)) return null;

  const sentences: SentenceDocument["sentences"] = [];
  const seen = new Set<string>();
  for (const rawSentence of value.document.sentences as unknown[]) {
    if (!isRecord(rawSentence) || typeof rawSentence.id !== "string" || !sentenceIdPattern.test(rawSentence.id)
      || seen.has(rawSentence.id) || typeof rawSentence.text !== "string" || !isWellFormedText(rawSentence.text)) return null;
    seen.add(rawSentence.id);
    sentences.push({ id: rawSentence.id, text: rawSentence.text });
  }

  const illustrationsBySentence: Record<SentenceId, string> = {};
  for (const [sentenceId, assetId] of Object.entries(value.illustrationsBySentence)) {
    if (!sentenceIdPattern.test(sentenceId) || !validOpaqueId(assetId)) return null;
    illustrationsBySentence[sentenceId] = assetId;
  }

  const nextSequence = value.document.nextSequence as number;
  const sequenceIds = sentences.map(({ id }) => Number(id.slice("sentence-".length)));
  if (sequenceIds.some((sequence) => !Number.isSafeInteger(sequence) || sequence < 1 || sequence >= nextSequence)) return null;

  return {
    version: 1,
    documentId: value.documentId,
    sourceDraft: value.sourceDraft,
    document: { sourceText: value.document.sourceText, sentences, nextSequence },
    hasPrepared: value.hasPrepared,
    mode: value.mode,
    voice: value.voice,
    backgroundAssetId: value.backgroundAssetId,
    illustrationsBySentence,
  };
}

function parseSummary(value: unknown): ProjectSummary | null {
  if (!isRecord(value) || !validOpaqueId(value.id) || typeof value.name !== "string" || !value.name.trim()
    || value.name.length > 120 || !Number.isSafeInteger(value.revision) || (value.revision as number) < 0
    || !validTimestamp(value.createdAt) || !validTimestamp(value.updatedAt)) return null;
  return { id: value.id, name: value.name, revision: value.revision as number, createdAt: value.createdAt, updatedAt: value.updatedAt };
}

function parseProject(value: unknown): ProjectRecord | null {
  const summary = parseSummary(value);
  if (!summary || !isRecord(value) || !Object.hasOwn(value, "snapshot")) return null;
  const snapshot = parseSnapshot(value.snapshot);
  return snapshot ? { ...summary, snapshot } : null;
}

function parseAudio(value: unknown): ProjectAudio | null {
  if (!isRecord(value) || typeof value.id !== "string" || !sentenceIdPattern.test(value.id)
    || typeof value.text !== "string" || !isWellFormedText(value.text)
    || typeof value.voice !== "string" || !value.voice || value.voice.length > 100
    || typeof value.configurationFingerprint !== "string" || !/^[a-f0-9]{64}$/.test(value.configurationFingerprint)
    || !validOpaqueId(value.assetId) || typeof value.durationSeconds !== "number"
    || !Number.isFinite(value.durationSeconds) || value.durationSeconds <= 0 || value.status !== "ready"
    || (value.reused !== undefined && typeof value.reused !== "boolean")) return null;
  return {
    id: value.id,
    text: value.text,
    voice: value.voice,
    configurationFingerprint: value.configurationFingerprint,
    assetId: value.assetId,
    durationSeconds: value.durationSeconds,
    status: "ready",
    ...(value.reused === undefined ? {} : { reused: value.reused }),
  };
}

function parseHistory(value: unknown): ProjectHistoryEntry | null {
  if (!isRecord(value) || !validOpaqueId(value.id) || !validOpaqueId(value.jobId) || !validOpaqueId(value.projectId)
    || !validTimestamp(value.createdAt) || (value.durationSeconds !== null
      && (typeof value.durationSeconds !== "number" || !Number.isFinite(value.durationSeconds) || value.durationSeconds <= 0))
    || (value.sizeBytes !== null && (!Number.isSafeInteger(value.sizeBytes) || (value.sizeBytes as number) < 0))
    || typeof value.available !== "boolean" || (value.reason !== undefined && value.reason !== null && typeof value.reason !== "string")) return null;
  let snapshot: ProjectHistoryEntry["snapshot"] = null;
  if (value.snapshot !== null) {
    if (!isRecord(value.snapshot) || !isRecord(value.snapshot.request)) return null;
    const editor = parseSnapshot(value.snapshot.editor);
    if (!editor) return null;
    snapshot = { editor, request: value.snapshot.request,
      ...(isRecord(value.snapshot.media) ? { media: value.snapshot.media } : {}) };
  }
  if (value.available && snapshot === null) return null;
  return {
    id: value.id,
    jobId: value.jobId,
    projectId: value.projectId,
    createdAt: value.createdAt,
    durationSeconds: value.durationSeconds as number | null,
    sizeBytes: value.sizeBytes as number | null,
    available: value.available,
    ...(typeof value.reason === "string" || value.reason === null ? { reason: value.reason } : {}),
    snapshot,
  };
}

function parseAttempt(value: unknown): ProjectAttempt | null {
  if (!isRecord(value) || !validOpaqueId(value.id) || !validOpaqueId(value.projectId) || !validOpaqueId(value.documentId)
    || (value.kind !== "speech" && value.kind !== "video") || typeof value.status !== "string" || value.status.length > 40
    || !(value.job === null || isRecord(value.job)) || !validOpaqueId(value.submissionToken)
    || !Number.isSafeInteger(value.revision) || (value.revision as number) < 0
    || !validTimestamp(value.createdAt) || !validTimestamp(value.updatedAt) || !Object.hasOwn(value, "snapshot")) return null;
  return {
    id: value.id,
    projectId: value.projectId,
    documentId: value.documentId,
    kind: value.kind,
    status: value.status,
    job: value.job,
    submissionToken: value.submissionToken,
    revision: value.revision as number,
    snapshot: value.snapshot,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  };
}

async function requestJson(url: string, init: RequestInit = {}): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for project storage.", "AbortError");
    throw new ProjectApiError("The local service could not confirm this project change. Retry the same save before starting another project.");
  }
  if (!response.ok) {
    if (response.status === 409) throw new ProjectApiError("This project changed since it was opened. Keep this draft and reload the saved project after confirming.", 409);
    if (response.status === 400 || response.status === 422) throw new ProjectApiError("The project data or name is invalid. Check the draft and try saving again.", response.status);
    if (response.status === 404) throw new ProjectApiError("This project is no longer available from the local service.", 404);
    throw new ProjectApiError("The local service could not save or open this project.", response.status);
  }
  try {
    return await response.json();
  } catch {
    throw new ProjectApiError("The local service returned an invalid project response. The save outcome may need to be checked.");
  }
}

function jsonPost(body: unknown, signal?: AbortSignal): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal };
}

export function createOpaqueToken(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function listProjects(signal?: AbortSignal): Promise<ProjectSummary[]> {
  const value = await requestJson("/api/projects", { signal });
  if (!isRecord(value) || !Array.isArray(value.projects)) throw new ProjectApiError("The local service returned an invalid project list.");
  const projects: ProjectSummary[] = [];
  for (const item of value.projects as unknown[]) {
    const project = parseSummary(item);
    if (!project || projects.some(({ id }) => id === project.id)) throw new ProjectApiError("The local service returned an invalid project list.");
    projects.push(project);
  }
  return projects;
}

export async function createProject(name: string, snapshot: ProjectSnapshot, operationToken: string, signal?: AbortSignal): Promise<ProjectRecord> {
  if (!opaqueId.test(operationToken)) throw new ProjectApiError("Invalid project operation token.");
  const value = await requestJson("/api/projects", jsonPost({ operationToken, name, snapshot }, signal));
  const project = parseProject(value);
  if (!project) throw new ProjectApiError("The local service returned an invalid saved project. The save outcome may need to be checked.");
  return project;
}

export async function saveProject(id: string, name: string, snapshot: ProjectSnapshot, expectedRevision: number,
  operationToken: string, signal?: AbortSignal): Promise<ProjectRecord> {
  if (!validOpaqueId(id) || !opaqueId.test(operationToken)) throw new ProjectApiError("Invalid project operation token.");
  const value = await requestJson(`/api/projects/${id}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operationToken, expectedRevision, name, snapshot }), signal,
  });
  const project = parseProject(value);
  if (!project || project.id !== id) throw new ProjectApiError("The local service returned an invalid saved project. The save outcome may need to be checked.");
  return project;
}

export async function getProject(id: string, signal?: AbortSignal): Promise<ProjectDetail> {
  if (!validOpaqueId(id)) throw new ProjectApiError("Invalid project identifier.");
  const value = await requestJson(`/api/projects/${id}`, { signal });
  const project = parseProject(value);
  if (!project || project.id !== id || !isRecord(value) || !Array.isArray(value.audio)
    || !Array.isArray(value.warnings) || !value.warnings.every((warning) => typeof warning === "string")
    || !Array.isArray(value.history) || !Array.isArray(value.attempts)) {
    throw new ProjectApiError("The local service returned an invalid project document.");
  }
  const audio: ProjectAudio[] = [];
  for (const item of value.audio as unknown[]) {
    const parsed = parseAudio(item);
    if (!parsed) throw new ProjectApiError("The local service returned invalid saved speech associations.");
    audio.push(parsed);
  }
  const history: ProjectHistoryEntry[] = [];
  for (const item of value.history as unknown[]) {
    const parsed = parseHistory(item);
    if (!parsed) throw new ProjectApiError("The local service returned invalid video history.");
    history.push(parsed);
  }
  const attempts: ProjectAttempt[] = [];
  for (const item of value.attempts as unknown[]) {
    const parsed = parseAttempt(item);
    if (!parsed) throw new ProjectApiError("The local service returned invalid generation history.");
    attempts.push(parsed);
  }
  return { ...project, audio, warnings: [...value.warnings] as string[], history, attempts };
}

export async function getProjectAttempt(projectId: string, submissionToken: string, signal?: AbortSignal): Promise<ProjectAttempt> {
  if (!validOpaqueId(projectId) || !opaqueId.test(submissionToken)) throw new ProjectApiError("Invalid generation submission token.");
  const value = await requestJson(`/api/projects/${projectId}/attempts/${submissionToken}`, { signal });
  const attempt = parseAttempt(value);
  if (!attempt || attempt.projectId !== projectId || attempt.submissionToken !== submissionToken) {
    throw new ProjectApiError("The local service returned an invalid generation status.");
  }
  return attempt;
}

export function isProjectSnapshot(value: unknown): value is ProjectSnapshot {
  return parseSnapshot(value) !== null;
}
