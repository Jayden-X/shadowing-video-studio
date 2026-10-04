const STORAGE_KEY = "shadowing-video-studio.project-cache.v1";
const opaqueId = /^[a-f0-9]{32}$/;
const sentenceIdPattern = /^sentence-\d+$/;

export type PendingProjectSubmission = {
  projectId: string;
  projectName: string;
  documentId: string;
  submissionToken: string;
  kind: "speech" | "video";
};

type ProjectAssetHint = {
  projectId: string;
  documentId: string;
  audioBySentence: Record<string, string>;
  backgroundAssetId: string | null;
  illustrationsBySentence: Record<string, string>;
};

type ProjectCache = {
  version: 1;
  lastProjectId: string | null;
  assetHints: ProjectAssetHint[];
  pendingSubmissions: PendingProjectSubmission[];
};

const emptyCache = (): ProjectCache => ({ version: 1, lastProjectId: null, assetHints: [], pendingSubmissions: [] });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseAssetMap(value: unknown): Record<string, string> | null {
  if (!isRecord(value)) return null;
  const parsed: Record<string, string> = {};
  for (const [sentenceId, assetId] of Object.entries(value)) {
    if (!sentenceIdPattern.test(sentenceId) || typeof assetId !== "string" || !opaqueId.test(assetId)) return null;
    parsed[sentenceId] = assetId;
  }
  return parsed;
}

function parseCache(value: unknown): ProjectCache {
  if (!isRecord(value) || value.version !== 1 || (value.lastProjectId !== null
    && (typeof value.lastProjectId !== "string" || !opaqueId.test(value.lastProjectId)))
    || !Array.isArray(value.assetHints) || !Array.isArray(value.pendingSubmissions)) return emptyCache();

  const assetHints: ProjectAssetHint[] = [];
  for (const raw of value.assetHints as unknown[]) {
    if (!isRecord(raw) || typeof raw.projectId !== "string" || !opaqueId.test(raw.projectId)
      || typeof raw.documentId !== "string" || !opaqueId.test(raw.documentId)
      || (raw.backgroundAssetId !== null && (typeof raw.backgroundAssetId !== "string" || !opaqueId.test(raw.backgroundAssetId)))) return emptyCache();
    const audioBySentence = parseAssetMap(raw.audioBySentence);
    const illustrationsBySentence = parseAssetMap(raw.illustrationsBySentence);
    if (!audioBySentence || !illustrationsBySentence) return emptyCache();
    assetHints.push({ projectId: raw.projectId, documentId: raw.documentId, audioBySentence,
      backgroundAssetId: raw.backgroundAssetId, illustrationsBySentence });
  }

  const pendingSubmissions: PendingProjectSubmission[] = [];
  for (const raw of value.pendingSubmissions as unknown[]) {
    if (!isRecord(raw) || typeof raw.projectId !== "string" || !opaqueId.test(raw.projectId)
      || typeof raw.projectName !== "string" || raw.projectName.length > 120
      || typeof raw.documentId !== "string" || !opaqueId.test(raw.documentId)
      || typeof raw.submissionToken !== "string" || !opaqueId.test(raw.submissionToken)
      || (raw.kind !== "speech" && raw.kind !== "video")) return emptyCache();
    pendingSubmissions.push({ projectId: raw.projectId, projectName: raw.projectName, documentId: raw.documentId,
      submissionToken: raw.submissionToken, kind: raw.kind });
  }
  return { version: 1, lastProjectId: value.lastProjectId as string | null, assetHints, pendingSubmissions };
}

function readCache(): ProjectCache {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === null ? emptyCache() : parseCache(JSON.parse(raw) as unknown);
  } catch {
    return emptyCache();
  }
}

function writeCache(cache: ProjectCache): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // The database remains authoritative; cache loss only removes convenience hints.
  }
}

export function getLastProjectId(): string | null {
  return readCache().lastProjectId;
}

export function setLastProjectId(projectId: string | null): void {
  const cache = readCache();
  writeCache({ ...cache, lastProjectId: projectId });
}

export function rememberProjectAssets(hint: ProjectAssetHint): void {
  const cache = readCache();
  const keyMatches = (item: ProjectAssetHint) => item.projectId === hint.projectId && item.documentId === hint.documentId;
  const assetHints = [...cache.assetHints.filter((item) => !keyMatches(item)), hint].slice(-20);
  writeCache({ ...cache, assetHints });
}

export function rememberPendingSubmission(submission: PendingProjectSubmission): void {
  const cache = readCache();
  const same = (item: PendingProjectSubmission) => item.projectId === submission.projectId
    && item.submissionToken === submission.submissionToken;
  const pendingSubmissions = [...cache.pendingSubmissions.filter((item) => !same(item)), submission].slice(-20);
  writeCache({ ...cache, pendingSubmissions });
}

export function forgetPendingSubmission(projectId: string, submissionToken: string): void {
  const cache = readCache();
  writeCache({ ...cache, pendingSubmissions: cache.pendingSubmissions.filter((item) =>
    item.projectId !== projectId || item.submissionToken !== submissionToken) });
}

export function pendingSubmissionsFor(projectId: string): PendingProjectSubmission[] {
  return readCache().pendingSubmissions.filter((submission) => submission.projectId === projectId);
}
