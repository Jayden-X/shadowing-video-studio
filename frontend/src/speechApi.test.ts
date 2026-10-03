import { afterEach, describe, expect, it, vi } from "vitest";
import { createSpeechJob, getSpeechCapabilities, getSpeechJob, getSpeechStatus, speechAssetUrl } from "./speechApi";

const snapshot = [{ id: "sentence-001", text: "Hello." }];
const binding = { voice: "Aiden", configurationFingerprint: "f".repeat(64) };
const job = { id: "a".repeat(32), status: "completed", error: null, ...binding,
  sentences: [{ ...snapshot[0], ...binding, status: "ready", assetId: "b".repeat(32), durationSeconds: 1.5, error: null, reused: false }] };
const capabilities = { available: true, reason: null, defaultVoice: "Aiden", model: "Qwen3-TTS", language: "English",
  voices: [{ id: "Aiden", label: "Aiden", configurationFingerprint: binding.configurationFingerprint }] };
function respond(value: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(value), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
afterEach(() => { vi.unstubAllGlobals(); });

describe("speech API", () => {
  it("sends only the frozen IDs/text and explicit force", async () => {
    const fetchMock = respond(job, 202);
    const controller = new AbortController();
    expect(await createSpeechJob(snapshot, true, binding, controller.signal)).toEqual(job);
    expect(fetchMock).toHaveBeenCalledWith("/api/speech/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sentences: snapshot, force: true, ...binding }), signal: controller.signal,
    });
  });
  it("queries the known job and exposes only controlled URLs", async () => {
    const fetchMock = respond(job);
    expect(await getSpeechJob(job.id, snapshot, binding)).toEqual(job);
    expect(fetchMock).toHaveBeenCalledWith(`/api/speech/jobs/${job.id}`, { signal: undefined });
    expect(speechAssetUrl("b".repeat(32))).toBe(`/api/speech/assets/${"b".repeat(32)}`);
    expect(() => speechAssetUrl("../secret")).toThrow(/identifier/);
    await expect(getSpeechJob("../secret", snapshot, binding)).rejects.toThrow(/invalid/);
  });
  it("loads provider capabilities and accepts only a listed default with SHA-256 fingerprints", async () => {
    respond(capabilities);
    expect(await getSpeechCapabilities()).toEqual(capabilities);
    respond({ ...capabilities, defaultVoice: "Unknown" });
    await expect(getSpeechCapabilities()).rejects.toThrow(/invalid speech progress/);
    respond({ ...capabilities, voices: [{ ...capabilities.voices[0], configurationFingerprint: "short" }] });
    await expect(getSpeechCapabilities()).rejects.toThrow(/invalid speech progress/);
  });
  it("maps readiness failure to safe actionable local text", async () => {
    respond({ available: false, reason: "raw path and credential", voice: "Aiden", model: "Qwen3-TTS-12Hz-0.6B-CustomVoice", backend: "cpu" });
    const status = await getSpeechStatus();
    expect(status.reason).toContain("configured workspace");
    expect(status.reason).not.toContain("credential");
  });
  it.each([
    {}, { ...job, extra: true }, { ...job, id: "../secret" }, { ...job, id: "c".repeat(32) },
    { ...job, status: "other" }, { ...job, sentences: [] }, { ...job, voice: "Other" },
    { ...job, configurationFingerprint: "e".repeat(64) },
    { ...job, sentences: [{ ...job.sentences[0], text: "Changed." }] },
    { ...job, sentences: [{ ...job.sentences[0], id: "wrong" }] },
    { ...job, sentences: [{ ...job.sentences[0], voice: "Other" }] },
    { ...job, sentences: [{ ...job.sentences[0], configurationFingerprint: "e".repeat(64) }] },
    { ...job, sentences: [{ ...job.sentences[0], assetId: "../secret" }] },
    { ...job, sentences: [{ ...job.sentences[0], durationSeconds: 0 }] },
    { ...job, sentences: [{ ...job.sentences[0], durationSeconds: null }] },
    { ...job, sentences: [{ ...job.sentences[0], error: "wrong" }] },
    { ...job, sentences: [{ ...job.sentences[0], status: "pending" }] },
    { ...job, status: "failed", error: null },
    { ...job, status: "failed", error: "failed", sentences: [{ ...job.sentences[0], status: "pending", assetId: null, durationSeconds: null }] },
  ])("rejects malformed or mismatched progress %#", async (value) => {
    respond(value);
    await expect(getSpeechJob(job.id, snapshot, binding)).rejects.toThrow(/invalid speech progress/);
  });
  it.each([400, 404, 409, 413, 422, 429, 500, 503])("maps HTTP %s without displaying server details", async (status) => {
    respond({ detail: "token=private stderr" }, status);
    await expect(createSpeechJob(snapshot, false, binding)).rejects.not.toThrow(/private/);
  });
  it("validates input before I/O", async () => {
    const fetchMock = respond(job);
    await expect(createSpeechJob([], false, binding)).rejects.toThrow(/review/);
    await expect(createSpeechJob([...snapshot, { id: "other", text: "Next." }], true, binding)).rejects.toThrow(/one sentence/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("rejects invalid JSON and preserves AbortError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("not JSON")));
    await expect(createSpeechJob(snapshot, false, binding)).rejects.toThrow(/invalid speech progress/);
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("private failure"); }));
    await expect(createSpeechJob(snapshot, false, binding, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  });
  it("validates availability strictly", async () => {
    respond({ available: true, reason: null, voice: "Aiden", model: "model", backend: "cpu", extra: true });
    await expect(getSpeechStatus()).rejects.toThrow(/invalid speech progress/);
  });
});
