import { useEffect, useRef, useState } from "react";
import type { SentenceItem } from "./domain/sentences";
import { selectJobAudio, type SpeechJob, type SpeechSelection } from "./domain/speech";
import { createSpeechJob, getSpeechJob, getSpeechStatus, SpeechApiError, type SpeechStatus } from "./speechApi";

const POLL_INTERVAL_MS = 1_000;
const WAIT_LIMIT_MS = 15 * 60_000;
const STATUS_LIMIT_MS = 15_000;

type Attempt = { snapshot: SentenceItem[]; scope: number; jobId: string | null };

export function useSpeech() {
  const [readiness, setReadiness] = useState<SpeechStatus | null>(null);
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
    getSpeechStatus(availability.signal).then((status) => {
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
    if (!attempt.current?.jobId) attempt.current = null;
    setNotice(`${timedOut ? "Stopped waiting after 15 minutes." : "Stopped waiting for speech."} The local job may still be running; this does not cancel generation. ${knownJob
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

  function finishWaiting() {
    controller.current = null;
    clearTimers();
    setWaiting(false);
  }

  function receive(result: SpeechJob, current: Attempt, token: number, signal: AbortSignal) {
    if (!mounted.current || sequence.current !== token || signal.aborted) return;
    current.jobId = result.id;
    setJob(result);
    if (current.scope === scope.current) setSelection((previous) => selectJobAudio(previous, result));
    if (result.status === "completed" || result.status === "failed") {
      attempt.current = null;
      finishWaiting();
      if (result.status === "failed") setError(result.error ?? "Speech generation failed. Successful audio is preserved.");
      else setNotice("Speech is ready. Listen to each sentence before generating a video.");
      return;
    }
    pollTimer.current = setTimeout(() => { void poll(current, token, signal); }, POLL_INTERVAL_MS);
  }

  function fail(errorValue: unknown, token: number, signal: AbortSignal) {
    if (!mounted.current || sequence.current !== token || signal.aborted) return;
    finishWaiting();
    setError(errorValue instanceof SpeechApiError ? errorValue.message : "Speech progress could not be loaded. Your text and existing audio are preserved.");
    if (errorValue instanceof SpeechApiError && errorValue.status === 404) {
      attempt.current = null;
      setJob(null);
      setSelection({});
      return;
    }
    // Keep a known job after network failure so resuming queries it rather than submitting twice.
    if (!attempt.current?.jobId) attempt.current = null;
  }

  async function poll(current: Attempt, token: number, signal: AbortSignal) {
    if (!current.jobId || signal.aborted || token !== sequence.current) return;
    try { receive(await getSpeechJob(current.jobId, current.snapshot, signal), current, token, signal); }
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

  async function generate(sentences: readonly SentenceItem[], force = false) {
    if (controller.current || attempt.current || !readiness?.available) return;
    const current: Attempt = { snapshot: sentences.map(({ id, text }) => ({ id, text })), scope: scope.current, jobId: null };
    attempt.current = current;
    setJob(null);
    const { token, signal } = beginWaiting();
    try { receive(await createSpeechJob(current.snapshot, force, signal), current, token, signal); }
    catch (errorValue: unknown) { fail(errorValue, token, signal); }
  }

  function resumeMonitoring() {
    const current = attempt.current;
    if (controller.current || !current?.jobId) return;
    const { token, signal } = beginWaiting();
    void poll(current, token, signal);
  }

  const outstanding = attempt.current !== null;
  return { readiness, checking, selection, job, waiting, outstanding, error, notice,
    generate, stopWaiting, resumeMonitoring, resetSelection, refreshReadiness };
}
