import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { createProjectApiTestServer, TEST_PROJECT_ID } from "./projectApiTestServer";

const jobId = "a".repeat(32);
const firstAsset = "b".repeat(32);
const nextAsset = "c".repeat(32);
const defaultBinding = { voice: "Aiden", configurationFingerprint: "f".repeat(64) };
const alternateBinding = { voice: "voice-2", configurationFingerprint: "e".repeat(64) };
const capabilities = { available: true, reason: null, defaultVoice: "Aiden", model: "Qwen3-TTS-12Hz-0.6B-CustomVoice", language: "English",
  voices: [{ id: "Aiden", label: "Aiden", configurationFingerprint: defaultBinding.configurationFingerprint },
    { id: alternateBinding.voice, label: "Alternative voice", configurationFingerprint: alternateBinding.configurationFingerprint }] };
type CapabilityFixture = Omit<typeof capabilities, "defaultVoice"> & { defaultVoice: string | null };
type Snapshot = { id: string; text: string }[];
function job(snapshot: Snapshot, status: "completed" | "running" | "failed" = "completed", asset = firstAsset,
  binding = defaultBinding, reused = false) {
  return { id: jobId, status, error: status === "failed" ? "raw private detail" : null, ...binding,
    sentences: snapshot.map((sentence, index) => ({ ...sentence,
      ...binding,
      status: status === "running" ? (index === 0 ? "generating" : "pending") : status === "failed" && index === 1 ? "failed" : "ready",
      assetId: status === "running" || (status === "failed" && index === 1) ? null : asset,
      durationSeconds: status === "running" || (status === "failed" && index === 1) ? null : 1.5,
      error: status === "failed" && index === 1 ? "raw private detail" : null, reused,
    })) };
}
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status }); }
function mockSpeech(create: (snapshot: Snapshot, force: boolean, init: RequestInit | undefined, binding: typeof defaultBinding) => Response | Promise<Response>,
  poll: (init: RequestInit | undefined) => Response | Promise<Response> = () => json({}),
  capabilityResponse: CapabilityFixture = capabilities) {
  const projectServer = createProjectApiTestServer();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const storageResponse = projectServer.handleStorage(url, init);
    if (storageResponse) return storageResponse;
    if (url === "/api/speech/status") return json({ available: true, reason: null, voice: "Aiden", model: "Qwen3-TTS-12Hz-0.6B-CustomVoice", backend: "cpu" });
    if (url === "/api/speech/capabilities") return json(capabilityResponse);
    if (url === "/api/video/status") return json({ available: true, reason: null });
    if (url === "/api/visuals/status") return json({ available: true, reason: null, maxUploadBytes: 10 * 1024 * 1024,
      formats: ["image/png", "image/jpeg", "image/webp"] });
    if (url === "/api/visuals/assets") return json({ assets: [] });
    if (url === "/api/visuals/cleanup/operations") return json({ operations: [] });
    if (url === "/api/text/providers") return json({ providers: ["codex", "deepseek"].map((id) => ({ id, label: id, available: false, reason: "unavailable" })) });
    const projectSpeech = await projectServer.submitSpeech(url, init, create);
    if (projectSpeech) return projectSpeech;
    const speechPoll = url.match(/^\/api\/speech\/jobs\/([a-f0-9]{32})$/);
    if (speechPoll) return projectServer.recordSpeechPoll(speechPoll[1], await poll(init));
    return json({ status: "ok" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function button(name: string) { return screen.getByRole("button", { name }) as HTMLButtonElement; }
function sentence(position: number) { return screen.getByRole("textbox", { name: `Sentence ${position}` }) as HTMLTextAreaElement; }
async function prepare(source = "Hello. Next.") {
  await act(async () => {});
  fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: source } });
  fireEvent.click(button("Prepare sentences"));
}
function previews() { return document.querySelectorAll("audio"); }
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.removeItem("shadowing-video-studio.project-cache.v1");
});

describe("sentence speech UI", () => {
  it("requires explicit generation, previews success and regenerates one frozen sentence", async () => {
    const fetchMock = mockSpeech((snapshot, force) => json(job(snapshot, "completed", force ? nextAsset : firstAsset), 202));
    render(<App />);
    await prepare();
    expect(previews()).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`)).toHaveLength(0);
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(previews()).toHaveLength(2);
    expect(previews()[0].getAttribute("src")).toBe(`/api/speech/assets/${firstAsset}`);
    expect(previews()[0].getAttribute("preload")).toBe("none");
    expect(previews()[0].hasAttribute("controls")).toBe(true);
    await act(async () => { fireEvent.click(button("Regenerate speech for sentence 1")); });
    expect(previews()[0].getAttribute("src")).toBe(`/api/speech/assets/${nextAsset}`);
    expect(previews()[1].getAttribute("src")).toBe(`/api/speech/assets/${firstAsset}`);
    const posts = fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`);
    const regeneration = JSON.parse(posts[1][1]?.body as string) as Record<string, unknown>;
    expect(regeneration).toMatchObject({ singleSentenceId: "sentence-001", configurationFingerprint: defaultBinding.configurationFingerprint,
      expectedRevision: 1, name: "Untitled project" });
    expect(sentence(1).value).toBe("Hello.");
  });
  it("shows reused audio and invalidates edited, merged, deleted, and replaced content", async () => {
    mockSpeech((snapshot) => json({ ...job(snapshot), sentences: job(snapshot).sentences.map((item) => ({ ...item, reused: true })) }, 202));
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(screen.getAllByText(/Reused/)).toHaveLength(2);
    fireEvent.change(sentence(1), { target: { value: "Changed." } });
    expect(previews()).toHaveLength(1);
    expect(screen.getByText(/Text changed/)).toBeTruthy();
    fireEvent.click(button("Merge sentence 2 with previous"));
    expect(previews()).toHaveLength(0);
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(previews()).toHaveLength(1);
    fireEvent.click(button("Delete sentence 1"));
    expect(previews()).toHaveLength(0);
    await prepare("Hello. Next.");
    fireEvent.click(button("Replace and prepare"));
    expect(previews()).toHaveLength(0);
  });
  it("selects only advertised voices and keeps audio bound to the selected configuration", async () => {
    const voiceRuns = new Map<string, number>();
    const fetchMock = mockSpeech((snapshot, _force, _init, binding) => {
      const run = (voiceRuns.get(binding.voice) ?? 0) + 1;
      voiceRuns.set(binding.voice, run);
      const asset = binding.voice === "Aiden" ? firstAsset : nextAsset;
      return json(job(snapshot, "completed", asset, binding, run > 1), 202);
    });
    render(<App />);
    await prepare("Hello.");
    const voiceSelect = screen.getByRole("combobox", { name: "Speech voice" }) as HTMLSelectElement;
    expect(voiceSelect.value).toBe("Aiden");
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(previews()).toHaveLength(1);

    const speechCallsBeforeSelection = fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`).length;
    fireEvent.change(voiceSelect, { target: { value: alternateBinding.voice } });
    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`)).toHaveLength(speechCallsBeforeSelection);
    expect(previews()).toHaveLength(0);
    expect(screen.getByText(/Saved audio uses Aiden voice/)).toBeTruthy();
    expect(button("Generate video").disabled).toBe(true);
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(previews()[0].getAttribute("src")).toBe(`/api/speech/assets/${nextAsset}`);
    const alternatePost = JSON.parse(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`)[1][1]?.body as string) as Record<string, unknown>;
    expect(alternatePost).toMatchObject({ configurationFingerprint: alternateBinding.configurationFingerprint });

    fireEvent.change(voiceSelect, { target: { value: "Aiden" } });
    expect(previews()).toHaveLength(0);
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(previews()[0].getAttribute("src")).toBe(`/api/speech/assets/${firstAsset}`);
    expect(screen.getAllByText(/Reused/)).toHaveLength(1);
    expect(button("Generate video").disabled).toBe(false);
  });
  it("requires an explicit voice choice when the backend has no default", async () => {
    const noDefault = { ...capabilities, defaultVoice: null };
    const fetchMock = mockSpeech((snapshot, _force, _init, binding) => json(job(snapshot, "completed", firstAsset, binding), 202), () => json({}), noDefault);
    render(<App />);
    await prepare("Hello.");
    const voiceSelect = screen.getByRole("combobox", { name: "Speech voice" }) as HTMLSelectElement;
    expect(voiceSelect.value).toBe("");
    expect(button("Generate speech").disabled).toBe(true);
    fireEvent.change(voiceSelect, { target: { value: alternateBinding.voice } });
    expect(button("Generate speech").disabled).toBe(false);
    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`)).toHaveLength(0);
  });
  it("preserves partial success and hides raw provider errors", async () => {
    mockSpeech((snapshot) => json(job(snapshot, "failed"), 202));
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(previews()).toHaveLength(1);
    expect(screen.getByRole("alert").textContent).toContain("Successful audio is preserved");
    expect(screen.queryByText(/raw private/)).toBeNull();
    expect(sentence(1).value).toBe("Hello.");
    expect(sentence(2).value).toBe("Next.");
  });
  it("locks editing, prevents duplicate submits, polls progress and unlocks after completion", async () => {
    vi.useFakeTimers();
    let snapshot: Snapshot = [];
    const fetchMock = mockSpeech((sentences) => { snapshot = sentences; return json(job(sentences, "running"), 202); }, () => json(job(snapshot)));
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); fireEvent.click(button("Generate speech")); });
    expect((screen.getByRole("combobox", { name: "Speech voice" }) as HTMLSelectElement).disabled).toBe(true);
    expect(sentence(1).disabled).toBe(true);
    expect(button("Add sentence").disabled).toBe(true);
    expect(button("Prepare sentences").disabled).toBe(true);
    expect(screen.getByText("Generating this sentence…")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`)).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(previews()).toHaveLength(2);
    expect(sentence(1).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "Stop waiting for speech" })).toBeNull();
  });
  it("recovers a saved Project Speech Job by submission token without submitting again", async () => {
    const fetchMock = mockSpeech((sentences, _force, _init, binding) => json(job(sentences, "running", firstAsset, binding), 202));
    const firstView = render(<App />);
    await prepare("Hello. Next.");
    await act(async () => { fireEvent.click(button("Generate speech")); });
    expect(button("Stop waiting for speech")).toBeTruthy();
    firstView.unmount();

    render(<App />);
    await act(async () => {});
    await act(async () => { fireEvent.click(button("Open last project")); });
    expect(button("Resume speech monitoring")).toBeTruthy();
    await act(async () => { fireEvent.click(button("Resume speech monitoring")); });

    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`)).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/attempts/${JSON.parse(window.localStorage.getItem("shadowing-video-studio.project-cache.v1") ?? "{}").pendingSubmissions?.[0]?.submissionToken}`)).toHaveLength(1);
    expect(screen.getByText("Generating speech · 0 of 2 sentences ready")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(button("Stop waiting for speech"));
  });
  it("stops monitoring without resubmitting and discards stale results after document replacement", async () => {
    vi.useFakeTimers();
    let snapshot: Snapshot = [];
    let resolvePoll!: (response: Response) => void;
    let pollSignal: AbortSignal | null | undefined;
    let pollCount = 0;
    const fetchMock = mockSpeech((sentences) => { snapshot = sentences; return json(job(sentences, "running"), 202); }, (init) => {
      pollCount += 1;
      if (pollCount > 1) return json(job(snapshot));
      pollSignal = init?.signal;
      return new Promise<Response>((resolve) => { resolvePoll = resolve; });
    });
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    fireEvent.click(button("Stop waiting for speech"));
    expect(pollSignal?.aborted).toBe(true);
    expect((screen.getByRole("combobox", { name: "Speech voice" }) as HTMLSelectElement).disabled).toBe(true);
    expect(sentence(1).disabled).toBe(false);
    expect(button("Generate speech").disabled).toBe(true);
    expect(screen.getByText(/does not cancel generation/)).toBeTruthy();
    await prepare("New document.");
    fireEvent.click(button("Replace and prepare"));
    await act(async () => { resolvePoll(json(job(snapshot))); });
    expect(previews()).toHaveLength(0);
    await act(async () => { fireEvent.click(button("Resume speech monitoring")); });
    expect(previews()).toHaveLength(0);
    expect(sentence(1).value).toBe("New document.");
    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/projects/${TEST_PROJECT_ID}/speech`)).toHaveLength(1);
    expect(button("Generate speech").disabled).toBe(false);
  });
  it("keeps old audio on regeneration failure and explains playback failure", async () => {
    let fail = false;
    mockSpeech((snapshot) => fail ? json({ detail: "private traceback" }, 500) : json(job(snapshot), 202));
    render(<App />);
    await prepare("Hello.");
    await act(async () => { fireEvent.click(button("Generate speech")); });
    fail = true;
    await act(async () => { fireEvent.click(button("Regenerate speech for sentence 1")); });
    expect(previews()).toHaveLength(1);
    expect(sentence(1).value).toBe("Hello.");
    fireEvent.error(previews()[0]);
    expect(screen.getAllByRole("alert").some((alert) => alert.textContent?.includes("could not be played"))).toBe(true);
    expect(screen.queryByText(/private traceback/)).toBeNull();
  });
  it("aborts pending polling and clears timers on unmount", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | null | undefined;
    let snapshot: Snapshot = [];
    const fetchMock = mockSpeech((sentences) => { snapshot = sentences; return json(job(sentences, "running"), 202); }, (init) => {
      signal = init?.signal;
      return new Promise<Response>(() => {});
    });
    const view = render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(15 * 60_000); });
    expect(fetchMock.mock.calls.filter(([url]) => url === `/api/speech/jobs/${jobId}`)).toHaveLength(1);
    expect(snapshot).toHaveLength(2);
  });
  it("bounds waiting and keeps a known job resumable after a polling failure", async () => {
    vi.useFakeTimers();
    mockSpeech((snapshot) => json(job(snapshot, "running"), 202), () => json({ detail: "private error" }, 503));
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(button("Resume speech monitoring")).toBeTruthy();
    expect(button("Generate speech").disabled).toBe(true);
    expect(sentence(1).disabled).toBe(false);
    expect(screen.queryByText(/private error/)).toBeNull();
  });
  it("ends a hanging poll after 15 minutes while preserving a resumable job", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | null | undefined;
    mockSpeech((snapshot) => json(job(snapshot, "running"), 202), (init) => {
      signal = init?.signal;
      return new Promise<Response>(() => {});
    });
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(15 * 60_000); });
    expect(signal?.aborted).toBe(true);
    expect(screen.getByText(/Stopped waiting after 15 minutes/)).toBeTruthy();
    expect(button("Resume speech monitoring")).toBeTruthy();
    expect(sentence(1).disabled).toBe(false);
    expect(sentence(1).value).toBe("Hello.");
  });
  it("clears an interrupted job when the service reports a restart failure", async () => {
    vi.useFakeTimers();
    let snapshot: Snapshot = [];
    mockSpeech((sentences) => { snapshot = sentences; return json(job(sentences, "running"), 202); }, () => json({
      ...job(snapshot, "failed"), error: "Speech interrupted by a service restart. Successful audio is preserved.",
    }));
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(screen.getByRole("alert").textContent).toContain("Check the local runtime, then retry");
    expect(screen.queryByRole("button", { name: "Resume speech monitoring" })).toBeNull();
    expect(button("Generate speech").disabled).toBe(false);
    expect(sentence(1).value).toBe("Hello.");
  });
  it("keeps an unconfirmed project submission resumable and ignores its late result", async () => {
    let resolve!: (response: Response) => void;
    let snapshot: Snapshot = [];
    let signal: AbortSignal | null | undefined;
    mockSpeech((sentences, _force, init) => {
      snapshot = sentences;
      signal = init?.signal;
      return new Promise<Response>((done) => { resolve = done; });
    });
    render(<App />);
    await prepare();
    await act(async () => { fireEvent.click(button("Generate speech")); });
    fireEvent.click(button("Stop waiting for speech"));
    expect(signal?.aborted).toBe(true);
    expect(screen.getByText(/does not cancel generation/)).toBeTruthy();
    expect(button("Resume speech monitoring")).toBeTruthy();
    expect(button("Generate speech").disabled).toBe(true);
    await act(async () => { resolve(json(job(snapshot), 202)); });
    expect(previews()).toHaveLength(0);
  });
  it("refreshes readiness without losing the edited document", async () => {
    let available = false;
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/speech/status") return json({ available, reason: available ? null : "unavailable", voice: "Aiden", model: "model", backend: "cpu" });
      if (url === "/api/speech/capabilities") return json({ ...capabilities, available, reason: available ? null : "unavailable" });
      if (url === "/api/text/providers") return json({ providers: ["codex", "deepseek"].map((id) => ({ id, label: id, available: false, reason: "unavailable" })) });
      return json({ status: "ok" });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await prepare("Keep my work.");
    expect(button("Generate speech").disabled).toBe(true);
    available = true;
    await act(async () => { fireEvent.click(button("Check speech availability")); });
    expect(button("Generate speech").disabled).toBe(false);
    expect(sentence(1).value).toBe("Keep my work.");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/speech/status")).toHaveLength(2);
  });
});
