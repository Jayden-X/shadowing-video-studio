import { useEffect, useRef, useState } from "react";
import type { SentenceItem } from "./domain/sentences";
import { selectJobAudio, type SpeechAudio, type SpeechBinding, type SpeechJob, type SpeechSelection } from "./domain/speech";
import { getProjectAttempt } from "./projectApi";
import type { ProjectAudio, ProjectSubmissionContext } from "./projectApi";
import { createProjectSpeechJob, createSpeechJob, getSpeechCapabilities, getSpeechJob, getSpeechStatus, SpeechApiError,
  validateProjectSpeechAttemptJob, type ProjectSpeechJob, type SpeechCapabilities, type SpeechStatus } from "./speechApi";

const POLL_INTERVAL_MS = 1_000;
const WAIT_LIMIT_MS = 15 * 60_000;
const STATUS_LIMIT_MS = 15_000;

type Attempt = { snapshot: SentenceItem[]; binding: SpeechBinding; scope: number; jobId: string | null;
  project: ProjectSubmissionContext | null; kind: "speech"; };

export function useSpeech() {
  const [readiness, setReadiness] = useState<SpeechStatus | null>(null);
  const [capabilities, setCapabilities] = useState<SpeechCapabilities | null>(null);
  const [selectedVoice, setSelectedVoice] = useState("");
  const [checking, setChecking] = useState(true);
  const [selection, setSelection] = useState<SpeechSelection>({});
  const [job, setJob] = useState<SpeechJob | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(false);
  const sequence = useRef(0);
  const scope = useRef(0);
  const attempt = useRef<Attempt | null>(null);
  const controller = useRef<AbortController | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const waitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const availabilityController = useRef<AbortController | null>(null);
  const availabilitySequence = useRef(0);
  const capabilitiesLoaded = useRef(false);
  const storedVoiceOverride = useRef<string | null>(null);
  const availabilityTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearTimers() {
    if (pollTimer.current !== null) clearTimeout(pollTimer.current);
    if (waitTimer.current !== null) clearTimeout(waitTimer.current);
    pollTimer.current = null;
    waitTimer.current = null;
  }

  function refreshReadiness() {
    if (availabilityTimer.current !== null) clearTimeout(availabilityTimer.current);
    availabilityController.current?.abort();
    const availability = new AbortController();
    availabilityController.current = availability;
    const token = ++availabilitySequence.current;
    setChecking(true);
    availabilityTimer.current = setTimeout(() => availability.abort(), STATUS_LIMIT_MS);
    Promise.all([getSpeechStatus(availability.signal), getSpeechCapabilities(availability.signal)]).then(([status, nextCapabilities]) => {
      if (!mounted.current || token !== availabilitySequence.current || availability.signal.aborted) return;
      setReadiness(status);
      setCapabilities(nextCapabilities);
      const firstCapabilities = !capabilitiesLoaded.current;
      capabilitiesLoaded.current = true;
      setSelectedVoice((current) => {
        if (!firstCapabilities) return nextCapabilities.voices.some((voice) => voice.id === current) ? current : "";
        if (storedVoiceOverride.current !== null) return storedVoiceOverride.current;
        return nextCapabilities.defaultVoice ?? "";
      });
    }).catch(() => {
      if (mounted.current && token === availabilitySequence.current) {
        setReadiness(null);
        setCapabilities(null);
      }
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
      availabilitySequence.current += 1;
      availabilityController.current?.abort();
      if (availabilityTimer.current !== null) clearTimeout(availabilityTimer.current);
      sequence.current += 1;
      controller.current?.abort();
      clearTimers();
    };
  }, []);

  function stopWaiting(timedOut = false) {
    sequence.current += 1;
    controller.current?.abort();
    controller.current = null;
    clearTimers();
    setWaiting(false);
    const knownJob = attempt.current?.jobId;
    if (!attempt.current?.jobId && !attempt.current?.project) attempt.current = null;
    setNotice(`${timedOut ? "Stopped waiting after 15 minutes." : "Stopped waiting for speech."} The local job may still be running; this does not cancel generation. ${knownJob || attempt.current?.project
      ? "Resume monitoring to check its result."
      : "The submission could not be confirmed. Check the local service before explicitly trying again."}`);
  }

  function resetSelection() {
    scope.current += 1;
    setSelection({});
    setError("");
    setNotice("");
    // A stopped job still occupies the service. Keep its identity until a terminal result.
    if (!attempt.current?.jobId) setJob(null);
  }

  function restoreProjectAudio(audio: readonly ProjectAudio[], voice: string) {
    storedVoiceOverride.current = voice;
    setSelectedVoice(voice);
    const restored: Record<string, SpeechAudio> = Object.create(null) as Record<string, SpeechAudio>;
    for (const item of audio) {
      restored[item.id] = { id: item.id, text: item.text, voice: item.voice,
        configurationFingerprint: item.configurationFingerprint, assetId: item.assetId,
        durationSeconds: item.durationSeconds, reused: item.reused ?? true };
    }
    setSelection(restored);
  }

  function resetProjectState() {
    storedVoiceOverride.current = null;
    setSelectedVoice(capabilities?.defaultVoice ?? "");
    setSelection({});
  }

  function finishWaiting() {
    controller.current = null;
    clearTimers();
    setWaiting(false);
  }

  function receive(result: SpeechJob | ProjectSpeechJob, current: Attempt, token: number, signal: AbortSignal) {
    if (!mounted.current || sequence.current !== token || signal.aborted) return;
    current.jobId = result.id;
    setJob(result);
    if ("projectRevision" in result) current.project?.onAccepted?.(result.projectRevision);
    if (current.scope === scope.current) setSelection((previous) => selectJobAudio(previous, result));
    if (result.status === "completed" || result.status === "failed") {
      attempt.current = null;
      finishWaiting();
      current.project?.onFinished?.();
      if (result.status === "failed") setError(result.error ?? "Speech generation failed. Successful audio is preserved.");
      else if (current.scope === scope.current) setNotice("Speech is ready. Listen to each sentence before generating a video.");
      else setNotice(`Speech for ${current.project?.projectName ?? "the earlier project"} has finished. Reopen that project to refresh its saved audio.`);
      if (result.status === "failed" && current.scope !== scope.current) {
        setNotice(`Speech for ${current.project?.projectName ?? "the earlier project"} failed. Its saved audio and current project were not changed.`);
      }
      return;
    }
    pollTimer.current = setTimeout(() => { void poll(current, token, signal); }, POLL_INTERVAL_MS);
  }

  function fail(errorValue: unknown, token: number, signal: AbortSignal) {
    if (!mounted.current || sequence.current !== token || signal.aborted) return;
    finishWaiting();
    setError(errorValue instanceof SpeechApiError ? errorValue.message : "Speech progress could not be loaded. Your text and existing audio are preserved.");
    if (errorValue instanceof SpeechApiError && errorValue.status === 404 && !attempt.current?.project) {
      attempt.current = null;
      setJob(null);
      setSelection({});
      return;
    }
    // Keep a known job after network failure so resuming queries it rather than submitting twice.
    if (!attempt.current?.jobId && !attempt.current?.project) attempt.current = null;
  }

  async function poll(current: Attempt, token: number, signal: AbortSignal) {
    if (!current.jobId || signal.aborted || token !== sequence.current) return;
    try { receive(await getSpeechJob(current.jobId, current.snapshot, current.binding, signal), current, token, signal); }
    catch (errorValue: unknown) { fail(errorValue, token, signal); }
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

  async function generate(sentences: readonly SentenceItem[], force = false, project?: ProjectSubmissionContext) {
    const voice = capabilities?.voices.find((item) => item.id === selectedVoice);
    if (controller.current || attempt.current || !readiness?.available || !capabilities?.available || !voice) return;
    const binding: SpeechBinding = { voice: voice.id, configurationFingerprint: voice.configurationFingerprint };
    const current: Attempt = { snapshot: sentences.map(({ id, text }) => ({ id, text })), binding, scope: scope.current,
      jobId: null, project: project ? { ...project } : null, kind: "speech" };
    attempt.current = current;
    setJob(null);
    const { token, signal } = beginWaiting();
    try {
      const result = project
        ? await createProjectSpeechJob(current.snapshot, current.binding, {
          projectId: project.projectId,
          documentId: project.documentId,
          expectedRevision: project.revision,
          name: project.name,
          snapshot: project.snapshot,
          submissionToken: project.submissionToken,
          ...(force ? { singleSentenceId: current.snapshot[0].id } : {}),
        }, signal)
        : await createSpeechJob(current.snapshot, force, current.binding, signal);
      receive(result, current, token, signal);
    }
    catch (errorValue: unknown) { fail(errorValue, token, signal); }
  }

  function restorePendingSubmission(project: ProjectSubmissionContext) {
    if (attempt.current) return false;
    attempt.current = { snapshot: [], binding: { voice: "", configurationFingerprint: "" }, scope: scope.current,
      jobId: null, project: { ...project }, kind: "speech" };
    setJob(null);
    setError("");
    setNotice(`Speech submission for ${project.projectName} needs its saved status checked. It will not be resubmitted automatically.`);
    return true;
  }

  async function querySubmission(current: Attempt, token: number, signal: AbortSignal) {
    const project = current.project;
    if (!project) return;
    try {
      const attemptRecord = await getProjectAttempt(project.projectId, project.submissionToken, signal);
      if (signal.aborted || token !== sequence.current) return;
      if (attemptRecord.kind !== "speech") throw new SpeechApiError("This submission token belongs to a different generation type.");
      project.onAccepted?.(attemptRecord.revision);
      if (attemptRecord.job === null) {
        finishWaiting();
        setNotice(`Speech submission for ${project.projectName} is recorded, but no job status is available yet. Check again later; it was not resubmitted.`);
        return;
      }
      if (!isRecord(attemptRecord.job) || !Array.isArray(attemptRecord.job.sentences)
        || typeof attemptRecord.job.voice !== "string" || typeof attemptRecord.job.configurationFingerprint !== "string") {
        throw new SpeechApiError("The local service returned invalid speech attempt details.");
      }
      const attemptSnapshot = (attemptRecord.job.sentences as unknown[]).map((sentence) => {
        if (!isRecord(sentence) || typeof sentence.id !== "string" || typeof sentence.text !== "string") {
          throw new SpeechApiError("The local service returned invalid speech attempt details.");
        }
        return { id: sentence.id, text: sentence.text };
      });
      current.snapshot = attemptSnapshot;
      current.binding = { voice: attemptRecord.job.voice, configurationFingerprint: attemptRecord.job.configurationFingerprint };
      current.jobId = typeof attemptRecord.job.id === "string" ? attemptRecord.job.id : null;
      const result = validateProjectSpeechAttemptJob(attemptRecord.job, current.snapshot, current.binding);
      receive(result, current, token, signal);
    } catch (errorValue: unknown) {
      fail(errorValue, token, signal);
    }
  }

  function resumeMonitoring() {
    const current = attempt.current;
    if (controller.current || (!current?.jobId && !current?.project)) return;
    const { token, signal } = beginWaiting();
    if (current.jobId) void poll(current, token, signal);
    else void querySubmission(current, token, signal);
  }

  function chooseVoice(voice: string) {
    if (controller.current || attempt.current) return;
    if (voice === "" || capabilities?.voices.some((item) => item.id === voice)) {
      setSelectedVoice(voice);
      setError("");
      setNotice(voice ? `Selected ${capabilities?.voices.find((item) => item.id === voice)?.label ?? "voice"}. Generate speech to create or reuse audio for this voice.` : "Choose a supported voice before generating speech.");
    }
  }

  const outstanding = attempt.current !== null;
  const selected = capabilities?.voices.find((voice) => voice.id === selectedVoice);
  const binding = selected ? { voice: selected.id, configurationFingerprint: selected.configurationFingerprint } : null;
  const outstandingInfo = attempt.current?.project ? {
    projectId: attempt.current.project.projectId,
    projectName: attempt.current.project.projectName,
    documentId: attempt.current.project.documentId,
    submissionToken: attempt.current.project.submissionToken,
  } : null;
  return { readiness, capabilities, selectedVoice, binding, checking, selection, job, waiting, outstanding, outstandingInfo, error, notice,
    chooseVoice,
    generate, stopWaiting, resumeMonitoring, restoreProjectAudio, resetProjectState, restorePendingSubmission, resetSelection, refreshReadiness };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
