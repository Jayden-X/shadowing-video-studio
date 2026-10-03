import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const jobId = "a".repeat(32);
const speechAsset = "b".repeat(32);
const firstExport = "c".repeat(32);
const nextExport = "d".repeat(32);
type Snapshot = { id: string; text: string; assetId: string }[];
function videoJob(total: number, status: "completed" | "running" | "failed" = "completed", assetId = firstExport) {
  return { id: jobId, status, completedSentences: status === "completed" ? total : 0, totalSentences: total,
    assetId: status === "completed" ? assetId : null, durationSeconds: status === "completed" ? 13 : null,
    error: status === "failed" ? "private stderr" : null };
}
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status }); }
function mockVideo(create: (snapshot: Snapshot, init: RequestInit | undefined) => Response | Promise<Response>,
  poll: (init: RequestInit | undefined) => Response | Promise<Response> = () => json({})) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/video/status") return json({ available: true, reason: null });
    if (url === "/api/speech/status") return json({ available: true, reason: null, voice: "Aiden", model: "Qwen3-TTS-12Hz-0.6B-CustomVoice", backend: "cpu" });
    if (url === "/api/text/providers") return json({ providers: ["codex", "deepseek"].map((id) => ({ id, label: id, available: false, reason: "unavailable" })) });
    if (url === "/api/speech/jobs") {
      const { sentences } = JSON.parse(init?.body as string) as { sentences: { id: string; text: string }[] };
      return json({ id: "e".repeat(32), status: "completed", error: null,
        sentences: sentences.map((sentence) => ({ ...sentence, status: "ready", assetId: speechAsset, durationSeconds: 1.5, error: null, reused: false })) }, 202);
    }
    if (url === "/api/video/jobs") {
      const { sentences } = JSON.parse(init?.body as string) as { sentences: Snapshot };
      return create(sentences, init);
    }
    if (url === `/api/video/jobs/${jobId}`) return poll(init);
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
async function generateSpeech() { await act(async () => { fireEvent.click(button("Generate speech")); }); }
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("video export workflow", () => {
  it("requires current speech, freezes an explicit export, previews/downloads, and keeps prior exports", async () => {
    let calls = 0;
    const fetchMock = mockVideo((snapshot) => { calls += 1; return json(videoJob(snapshot.length, "completed", calls === 1 ? firstExport : nextExport), 202); });
    render(<App />);
    await prepare();
    expect(button("Generate video").disabled).toBe(true);
    await generateSpeech();
    expect(button("Generate video").disabled).toBe(false);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/video/jobs")).toHaveLength(0);
    await act(async () => { fireEvent.click(button("Generate video")); });
    const preview = document.querySelector("video");
    expect(preview?.getAttribute("src")).toBe(`/api/video/assets/${firstExport}`);
    expect(preview?.hasAttribute("controls")).toBe(true);
    expect(preview?.getAttribute("preload")).toBe("none");
    expect(screen.getByRole("link", { name: "Download MP4" }).getAttribute("href")).toBe(`/api/video/assets/${firstExport}?download=true`);
    const posts = fetchMock.mock.calls.filter(([url]) => url === "/api/video/jobs");
    expect(JSON.parse(posts[0][1]?.body as string)).toEqual({ sentences: [
      { id: "sentence-001", text: "Hello.", assetId: speechAsset }, { id: "sentence-002", text: "Next.", assetId: speechAsset },
    ] });
    await act(async () => { fireEvent.click(button("Generate video")); });
    expect(within(screen.getByRole("list", { name: "Exports in this session" })).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Download export 1" }).getAttribute("href")).toContain(firstExport);
    expect(document.querySelector("video")?.getAttribute("src")).toContain(nextExport);
    fireEvent.change(sentence(1), { target: { value: "Changed." } });
    expect(button("Generate video").disabled).toBe(true);
    expect(screen.getByRole("link", { name: "Download export 1" })).toBeTruthy();
  });
  it("preserves speech, text and an earlier export after renderer or playback failure", async () => {
    let fail = false;
    mockVideo((snapshot) => json(videoJob(snapshot.length, fail ? "failed" : "completed"), 202));
    render(<App />);
    await prepare();
    await generateSpeech();
    await act(async () => { fireEvent.click(button("Generate video")); });
    fail = true;
    await act(async () => { fireEvent.click(button("Generate video")); });
    expect(screen.getByRole("alert").textContent).toContain("speech and prior exports are preserved");
    expect(screen.queryByText(/private stderr/)).toBeNull();
    expect(sentence(1).value).toBe("Hello.");
    expect(document.querySelectorAll("audio")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Download export 1" })).toBeTruthy();
    expect(button("Generate video").disabled).toBe(false);
    fireEvent.error(document.querySelector("video")!);
    expect(screen.getAllByRole("alert").some((alert) => alert.textContent?.includes("export could not be played"))).toBe(true);
  });
  it("serializes clicks and keeps a late export accessible without changing a replacement document", async () => {
    vi.useFakeTimers();
    let total = 0;
    let resolvePoll!: (response: Response) => void;
    let signal: AbortSignal | null | undefined;
    let polls = 0;
    const fetchMock = mockVideo((snapshot) => { total = snapshot.length; return json(videoJob(total, "running"), 202); }, (init) => {
      polls += 1;
      if (polls > 1) return json(videoJob(total));
      signal = init?.signal;
      return new Promise<Response>((resolve) => { resolvePoll = resolve; });
    });
    render(<App />);
    await prepare();
    await generateSpeech();
    await act(async () => { fireEvent.click(button("Generate video")); fireEvent.click(button("Generate video")); });
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/video/jobs")).toHaveLength(1);
    expect(sentence(1).disabled).toBe(true);
    expect(button("Generate speech").disabled).toBe(true);
    expect(button("Prepare sentences").disabled).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    fireEvent.click(button("Stop waiting for video"));
    expect(signal?.aborted).toBe(true);
    expect(sentence(1).disabled).toBe(false);
    expect(button("Generate speech").disabled).toBe(true);
    expect(screen.getByText(/does not cancel rendering/)).toBeTruthy();
    await prepare("New document.");
    fireEvent.click(button("Replace and prepare"));
    await act(async () => { resolvePoll(json(videoJob(total))); });
    expect(document.querySelector("video")).toBeNull();
    await act(async () => { fireEvent.click(button("Resume video monitoring")); });
    expect(document.querySelector("video")?.getAttribute("src")).toBe(`/api/video/assets/${firstExport}`);
    expect(screen.getByRole("link", { name: "Download MP4" }).getAttribute("href")).toBe(`/api/video/assets/${firstExport}?download=true`);
    expect(sentence(1).value).toBe("New document.");
    expect(button("Generate speech").disabled).toBe(false);
    expect(button("Generate video").disabled).toBe(true);
    expect(screen.getByText(/earlier document's render has finished/)).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/video/jobs")).toHaveLength(1);
  });
});
