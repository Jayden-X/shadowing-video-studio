import { useEffect, useRef, useState } from "react";
import type { SpeechBinding } from "./domain/speech";
import { getProjectAttempt } from "./projectApi";
import type { ProjectSubmissionContext } from "./projectApi";
import { createProjectVideoJob, createVideoJob, getVideoJob, getVideoStatus, VideoApiError, type ProjectVideoJob, type VideoJob, type VideoSentence, type VideoStatus } from "./videoApi";

const WAIT_LIMIT_MS = 30 * 60_000;
const POLL_INTERVAL_MS = 1_000;
const STATUS_LIMIT_MS = 15_000;
type Attempt = { snapshot: VideoSentence[]; binding: SpeechBinding; backgroundAssetId: string | null; scope: number; jobId: string | null;
  project: ProjectSubmissionContext | null; kind: "video"; };
export type VideoExport = { assetId: string; durationSeconds: number; sentenceCount: number };

export function useVideo() {
  const [readiness, setReadiness] = useState<VideoStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [job, setJob] = useState<VideoJob | null>(null);
  const [exports, setExports] = useState<VideoExport[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(false);
  const scope = useRef(0);
  const sequence = useRef(0);
  const attempt = useRef<Attempt | null>(null);
  const controller = useRef<AbortController | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const waitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const availabilityController = useRef<AbortController | null>(null);
  const availabilityTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const availabilitySequence = useRef(0);

  function clearTimers() {
    if (pollTimer.current !== null) clearTimeout(pollTimer.current);
    if (waitTimer.current !== null) clearTimeout(waitTimer.current);
    pollTimer.current = null;
    waitTimer.current = null;
  }
  function refreshReadiness() {
    availabilityController.current?.abort();
    if (availabilityTimer.current !== null) clearTimeout(availabilityTimer.current);
    const availability = new AbortController();
    availabilityController.current = availability;
    const token = ++availabilitySequence.current;
    setChecking(true);
    availabilityTimer.current = setTimeout(() => availability.abort(), STATUS_LIMIT_MS);
    getVideoStatus(availability.signal).then((status) => {
      if (mounted.current && token === availabilitySequence.current && !availability.signal.aborted) setReadiness(status);
    }).catch(() => {
      if (mounted.current && token === availabilitySequence.current) setReadiness(null);
    }).finally(() => {
      if (token !== availabilitySequence.current) return;
      if (availabilityTimer.current !== null) clearTimeout(availabilityTimer.current);
      availabilityTimer.current = null;
      availabilityController.current = null;
      if (mounted.current) setChecking(false);
    });
  }
  useEffect(() => {
    mounted.current = true;
    refreshReadiness();
    return () => {
      mounted.current = false;
      sequence.current += 1;
      availabilitySequence.current += 1;
      controller.current?.abort();
      availabilityController.current?.abort();
      if (availabilityTimer.current !== null) clearTimeout(availabilityTimer.current);
      clearTimers();
    };
  }, []);

  function resetDocument() {
    scope.current += 1;
    setError("");
    setNotice("");
    if (!attempt.current?.jobId) setJob(null);
  }
  function finishWaiting() {
    controller.current = null;
    clearTimers();
    setWaiting(false);
  }
  function stopWaiting(timedOut = false) {
    sequence.current += 1;
    controller.current?.abort();
    const known = attempt.current?.jobId;
    if (!known && !attempt.current?.project) attempt.current = null;
    finishWaiting();
    setNotice(`${timedOut ? "Stopped waiting after 30 minutes." : "Stopped waiting for video."} The renderer may still be running; this does not cancel rendering. ${known || attempt.current?.project
      ? "Resume monitoring to check its result."
      : "The submission could not be confirmed. Check the local service before explicitly trying again."}`);
  }
  function fail(value: unknown, token: number, signal: AbortSignal) {
    if (!mounted.current || token !== sequence.current || signal.aborted) return;
    finishWaiting();
    setError(value instanceof VideoApiError ? value.message : "Video progress could not be loaded. Your speech and prior exports are preserved.");
    if (value instanceof VideoApiError && value.status === 404 && !attempt.current?.project) {
      attempt.current = null;
      setJob(null);
    } else if (!attempt.current?.jobId && !attempt.current?.project) attempt.current = null;
  }
  function receive(result: VideoJob | ProjectVideoJob, current: Attempt, token: number, signal: AbortSignal) {
    if (!mounted.current || token !== sequence.current || signal.aborted) return;
    current.jobId = result.id;
    setJob(result);
    if ("projectRevision" in result) current.project?.onAccepted?.(result.projectRevision);
    if (result.status === "completed" || result.status === "failed") {
      attempt.current = null;
      finishWaiting();
      current.project?.onFinished?.();
      const output = result.status === "completed" && result.assetId !== null && result.durationSeconds !== null
        ? { assetId: result.assetId, durationSeconds: result.durationSeconds, sentenceCount: result.totalSentences }
        : null;
      if (output) {
        setExports((previous) => previous.some((item) => item.assetId === output.assetId) ? previous : [...previous, output]);
      }
      if (current.scope !== scope.current) {
        setNotice(result.status === "completed"
          ? `The render for ${current.project?.projectName ?? "the earlier document"} has finished. Open that project to refresh its history; current dialogue and audio were not changed.`
          : `The render for ${current.project?.projectName ?? "the earlier document"} failed. Current dialogue and audio were not changed.`);
        return;
      }
      if (result.status === "failed") setError(result.error ?? "Video rendering failed. Your speech and prior exports are preserved.");
      else if (output) setNotice("Video is ready. Preview it and download the MP4.");
      return;
    }
    pollTimer.current = setTimeout(() => { void poll(current, token, signal); }, POLL_INTERVAL_MS);
  }
  async function poll(current: Attempt, token: number, signal: AbortSignal) {
    if (!current.jobId || signal.aborted || token !== sequence.current) return;
    try { receive(await getVideoJob(current.jobId, current.snapshot.length, signal), current, token, signal); }
    catch (value: unknown) { fail(value, token, signal); }
  }
  function beginWaiting() {
    const token = ++sequence.current;
    const active = new AbortController();
    controller.current = active;
    setWaiting(true);
    setError("");
    setNotice("");
    waitTimer.current = setTimeout(() => stopWaiting(true), WAIT_LIMIT_MS);
    return { token, signal: active.signal };
  }
  async function generate(sentences: readonly VideoSentence[], binding: SpeechBinding, backgroundAssetId: string | null = null,
    project?: ProjectSubmissionContext) {
    if (controller.current || attempt.current || !readiness?.available) return;
    const current: Attempt = {
      snapshot: sentences.map(({ id, text, assetId, illustrationAssetId }) => ({ id, text, assetId, illustrationAssetId })),
      binding: { voice: binding.voice, configurationFingerprint: binding.configurationFingerprint },
      backgroundAssetId,
      scope: scope.current,
      jobId: null,
      project: project ? { ...project } : null,
      kind: "video",
    };
    attempt.current = current;
    setJob(null);
    const { token, signal } = beginWaiting();
    try {
      const result = project
        ? await createProjectVideoJob(current.snapshot, current.binding, {
          projectId: project.projectId,
          documentId: project.documentId,
          expectedRevision: project.revision,
          name: project.name,
          snapshot: project.snapshot,
          submissionToken: project.submissionToken,
        }, signal)
        : await createVideoJob(current.snapshot, current.binding, current.backgroundAssetId, signal);
      receive(result, current, token, signal);
    }
    catch (value: unknown) { fail(value, token, signal); }
  }
  function restorePendingSubmission(project: ProjectSubmissionContext) {
    if (attempt.current) return false;
    attempt.current = { snapshot: [], binding: { voice: "", configurationFingerprint: "" }, backgroundAssetId: null,
      scope: scope.current, jobId: null, project: { ...project }, kind: "video" };
    setJob(null);
    setError("");
    setNotice(`Video submission for ${project.projectName} needs its saved status checked. It will not be resubmitted automatically.`);
    return true;
  }
  async function querySubmission(current: Attempt, token: number, signal: AbortSignal) {
    const project = current.project;
    if (!project) return;
    try {
      const attemptRecord = await getProjectAttempt(project.projectId, project.submissionToken, signal);
      if (signal.aborted || token !== sequence.current) return;
      if (attemptRecord.kind !== "video") throw new VideoApiError("This submission token belongs to a different generation type.");
      project.onAccepted?.(attemptRecord.revision);
      if (attemptRecord.job === null) {
        finishWaiting();
        setNotice(`Video submission for ${project.projectName} is recorded, but no job status is available yet. Check again later; it was not resubmitted.`);
        return;
      }
      if (!isRecord(attemptRecord.job) || typeof attemptRecord.job.id !== "string"
        || typeof attemptRecord.job.totalSentences !== "number" || !Number.isInteger(attemptRecord.job.totalSentences)) {
        throw new VideoApiError("The local service returned invalid video attempt details.");
      }
      current.jobId = attemptRecord.job.id;
      current.snapshot = Array.from({ length: attemptRecord.job.totalSentences }, () => ({ id: "", text: "", assetId: "" }));
      receive(await getVideoJob(current.jobId, current.snapshot.length, signal), current, token, signal);
    } catch (value: unknown) {
      fail(value, token, signal);
    }
  }
  function resumeMonitoring() {
    const current = attempt.current;
    if (controller.current || (!current?.jobId && !current?.project)) return;
    const { token, signal } = beginWaiting();
    if (current.jobId) void poll(current, token, signal);
    else void querySubmission(current, token, signal);
  }
  const outstandingInfo = attempt.current?.project ? {
    projectId: attempt.current.project.projectId,
    projectName: attempt.current.project.projectName,
    documentId: attempt.current.project.documentId,
    submissionToken: attempt.current.project.submissionToken,
  } : null;
  return { readiness, checking, job, exports, waiting, outstanding: attempt.current !== null, outstandingInfo, error, notice,
    generate, stopWaiting, resumeMonitoring, restorePendingSubmission, resetDocument, refreshReadiness };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
