type TestSentence = { id: string; text: string };
type TestSnapshot = {
  version: 1;
  documentId: string;
  sourceDraft: string;
  document: { sourceText: string; sentences: TestSentence[]; nextSequence: number };
  hasPrepared: boolean;
  mode: "manual" | "ai";
  voice: string;
  backgroundAssetId: string | null;
  illustrationsBySentence: Record<string, string>;
};
type JsonRecord = Record<string, unknown>;
type SpeechCreator = (sentences: TestSentence[], force: boolean, init: RequestInit | undefined,
  binding: { voice: string; configurationFingerprint: string }) => Response | Promise<Response>;
type VideoSentence = TestSentence & { assetId: string; illustrationAssetId?: string | null };
type VideoCreator = (sentences: VideoSentence[], init: RequestInit | undefined) => Response | Promise<Response>;

const PROJECT_ID = "9".repeat(32);
const CREATED_AT = "2026-10-04T00:00:00Z";
const timestamp = () => new Date().toISOString();

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function bodyOf(init: RequestInit | undefined): JsonRecord {
  if (typeof init?.body !== "string") return {};
  try {
    const parsed: unknown = JSON.parse(init.body);
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function responseJson(value: unknown): JsonRecord {
  return isRecord(value) ? value : {};
}

export function createProjectApiTestServer() {
  let project: { id: string; name: string; revision: number; snapshot: TestSnapshot; createdAt: string; updatedAt: string } | null = null;
  let audio: JsonRecord[] = [];
  let history: JsonRecord[] = [];
  const attempts = new Map<string, JsonRecord>();
  const pendingVideos = new Map<string, { snapshot: TestSnapshot; request: JsonRecord }>();

  function addHistory(job: JsonRecord, snapshot: TestSnapshot, request: JsonRecord) {
    if (typeof job.assetId !== "string" || typeof job.durationSeconds !== "number" || typeof job.id !== "string") return;
    if (history.some((item) => item.id === job.assetId)) return;
    const media = { assetId: job.assetId };
    const audioAssetIds = isRecord(request.audioAssetIds) ? request.audioAssetIds : {};
    history = [...history, { id: job.assetId, jobId: job.id, projectId: project?.id, createdAt: timestamp(),
      durationSeconds: job.durationSeconds, sizeBytes: 1024, sha256: "a".repeat(64), available: true,
      snapshot: { editor: snapshot, request: { voice: snapshot.voice, configurationFingerprint: request.configurationFingerprint,
        backgroundAssetId: snapshot.backgroundAssetId, audioAssetIds }, media } }];
  }

  function summary() {
    if (!project) return [];
    const { id, name, revision, createdAt, updatedAt } = project;
    return [{ id, name, revision, createdAt, updatedAt }];
  }

  function detail() {
    if (!project) return null;
    return { ...project, audio, warnings: [], history, attempts: [...attempts.values()] };
  }

  function handleStorage(url: string, init?: RequestInit): Response | null {
    const method = init?.method ?? "GET";
    if (url === "/api/projects/retained/resources" && method === "GET") return response({ projects: [] });
    if (url === "/api/projects") {
      if (method === "GET") return response({ projects: summary() });
      if (method === "POST") {
        const body = bodyOf(init);
        if (!isRecord(body.snapshot)) return response({ detail: "invalid snapshot" }, 422);
        const now = timestamp();
        project = { id: PROJECT_ID, name: typeof body.name === "string" ? body.name : "Untitled project",
          revision: 1, snapshot: body.snapshot as unknown as TestSnapshot, createdAt: now, updatedAt: now };
        return response(project, 201);
      }
      return response({ detail: "unsupported method" }, 405);
    }

    const attemptMatch = url.match(new RegExp(`^/api/projects/${PROJECT_ID}/attempts/([a-f0-9]{32})$`));
    if (attemptMatch && method === "GET") return attempts.has(attemptMatch[1])
      ? response(attempts.get(attemptMatch[1])) : response({ detail: "missing attempt" }, 404);

    const projectMatch = url.match(new RegExp(`^/api/projects/${PROJECT_ID}$`));
    if (projectMatch && method === "GET") return detail() ? response(detail()) : response({ detail: "missing project" }, 404);
    if (projectMatch && method === "PUT") {
      const body = bodyOf(init);
      if (!project || !isRecord(body.snapshot)) return response({ detail: "missing project" }, 404);
      const expectedRevision = typeof body.expectedRevision === "number" ? body.expectedRevision : project.revision;
      const changed = project.name !== body.name || JSON.stringify(project.snapshot) !== JSON.stringify(body.snapshot);
      project = { ...project, name: typeof body.name === "string" ? body.name : project.name,
        snapshot: body.snapshot as unknown as TestSnapshot,
        revision: Math.max(project.revision, expectedRevision + (changed ? 1 : 0)), updatedAt: timestamp() };
      return response(project);
    }
    return null;
  }

  async function submitSpeech(url: string, init: RequestInit | undefined, create: SpeechCreator): Promise<Response | null> {
    if (!new RegExp(`^/api/projects/${PROJECT_ID}/speech$`).test(url)) return null;
    const body = bodyOf(init);
    if (!project || !isRecord(body.snapshot) || typeof body.operationToken !== "string") return response({ detail: "project not found" }, 404);
    const snapshot = body.snapshot as unknown as TestSnapshot;
    const configuredSentences = Array.isArray(snapshot.document?.sentences) ? snapshot.document.sentences : [];
    const singleSentenceId = typeof body.singleSentenceId === "string" ? body.singleSentenceId : null;
    const sentences = singleSentenceId ? configuredSentences.filter((item) => item.id === singleSentenceId) : configuredSentences;
    const binding = { voice: snapshot.voice, configurationFingerprint: String(body.configurationFingerprint ?? "") };
    const baseResponse = await create(sentences, singleSentenceId !== null, init, binding);
    if (!baseResponse.ok) return baseResponse;
    const job = responseJson(await baseResponse.clone().json().catch(() => null));
    const decorated = { ...job, projectId: project.id, documentId: snapshot.documentId,
      projectRevision: project.revision, submissionToken: body.operationToken };
    const jobSentences = Array.isArray(job.sentences) ? job.sentences.filter(isRecord) : [];
    const currentAudio = new Map(audio.map((item) => [item.id, item]));
    for (const item of jobSentences) {
      if (item.status === "ready" && typeof item.assetId === "string" && typeof item.durationSeconds === "number") {
        currentAudio.set(String(item.id), { id: item.id, text: item.text, voice: job.voice,
          configurationFingerprint: job.configurationFingerprint, assetId: item.assetId,
          durationSeconds: item.durationSeconds, status: "ready", ...(typeof item.reused === "boolean" ? { reused: item.reused } : {}) });
      }
    }
    audio = [...currentAudio.values()];
    attempts.set(body.operationToken, { id: job.id, projectId: project.id, documentId: snapshot.documentId, kind: "speech",
      status: job.status, job: decorated, submissionToken: body.operationToken, revision: project.revision,
      snapshot: { editor: snapshot, request: { configurationFingerprint: body.configurationFingerprint,
        singleSentenceId }, media: {} },
      createdAt: CREATED_AT, updatedAt: timestamp() });
    return response(decorated, baseResponse.status);
  }

  async function recordSpeechPoll(jobId: string, result: Response): Promise<Response> {
    if (!result.ok) return result;
    const source = [...attempts.values()].find((attempt) => attempt.kind === "speech" && attempt.id === jobId);
    if (!source || !isRecord(source.job)) return result;
    const job = responseJson(await result.clone().json().catch(() => null));
    const decorated: JsonRecord = { ...job, projectId: source.projectId, documentId: source.documentId,
      projectRevision: source.revision, submissionToken: source.submissionToken };
    source.job = decorated;
    source.status = decorated.status;
    source.updatedAt = timestamp();
    attempts.set(String(source.submissionToken), source);
    return response(decorated, result.status);
  }

  async function submitVideo(url: string, init: RequestInit | undefined, create: VideoCreator): Promise<Response | null> {
    if (!new RegExp(`^/api/projects/${PROJECT_ID}/video$`).test(url)) return null;
    const body = bodyOf(init);
    if (!project || !isRecord(body.snapshot) || typeof body.operationToken !== "string") return response({ detail: "project not found" }, 404);
    const snapshot = body.snapshot as unknown as TestSnapshot;
    const audioBySentence = isRecord(body.audioAssetIds) ? body.audioAssetIds : {};
    const sentences = (Array.isArray(snapshot.document?.sentences) ? snapshot.document.sentences : []).map((item) => ({
      ...item,
      assetId: String(audioBySentence[item.id] ?? ""),
      ...(snapshot.illustrationsBySentence[item.id] ? { illustrationAssetId: snapshot.illustrationsBySentence[item.id] } : {}),
    }));
    const baseResponse = await create(sentences, init);
    if (!baseResponse.ok) return baseResponse;
    const job = responseJson(await baseResponse.clone().json().catch(() => null));
    const decorated = { ...job, projectId: project.id, documentId: snapshot.documentId,
      projectRevision: project.revision, submissionToken: body.operationToken };
    const attempt = { id: job.id, projectId: project.id, documentId: snapshot.documentId, kind: "video",
      status: job.status, job: decorated, submissionToken: body.operationToken, revision: project.revision,
      snapshot, createdAt: CREATED_AT, updatedAt: timestamp() };
    attempts.set(body.operationToken, attempt);
    if (job.status === "completed" && typeof job.assetId === "string" && typeof job.durationSeconds === "number") {
      addHistory(job, snapshot, body);
    } else if (typeof job.id === "string") pendingVideos.set(job.id, { snapshot, request: body });
    return response(decorated, baseResponse.status);
  }

  async function recordVideoPoll(jobId: string, result: Response): Promise<Response> {
    const source = pendingVideos.get(jobId);
    if (source && result.ok) {
      const job = responseJson(await result.clone().json().catch(() => null));
      if (job.status === "completed") {
        addHistory(job, source.snapshot, source.request);
        pendingVideos.delete(jobId);
      }
    }
    return result;
  }

  return { handleStorage, submitSpeech, recordSpeechPoll, submitVideo, recordVideoPoll };
}

export const TEST_PROJECT_ID = PROJECT_ID;
