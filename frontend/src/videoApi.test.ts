import { afterEach, describe, expect, it, vi } from "vitest";
import { createVideoJob, getVideoJob, videoAssetUrl } from "./videoApi";

const jobId = "a".repeat(32);
const assetId = "b".repeat(32);
const sentences = [{ id: "sentence-001", text: "Hello.", assetId: "c".repeat(32) }];
const binding = { voice: "Aiden", configurationFingerprint: "f".repeat(64) };
const completed = { id: jobId, status: "completed", completedSentences: 1, totalSentences: 1,
  assetId, durationSeconds: 6.5, error: null };
function respond(value: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(value), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
afterEach(() => { vi.unstubAllGlobals(); });

describe("video API boundary", () => {
  it("freezes only canonical sentence and asset IDs and serves opaque export URLs", async () => {
    const fetchMock = respond(completed, 202);
    const controller = new AbortController();
    const illustrationId = "d".repeat(32);
    const backgroundId = "e".repeat(32);
    const frozenSentences = [{ ...sentences[0], illustrationAssetId: illustrationId }];
    expect(await createVideoJob(frozenSentences, binding, backgroundId, controller.signal)).toEqual(completed);
    expect(fetchMock).toHaveBeenCalledWith("/api/video/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sentences: frozenSentences, ...binding, backgroundAssetId: backgroundId }), signal: controller.signal,
    });
    expect(videoAssetUrl(assetId)).toBe(`/api/video/assets/${assetId}`);
    expect(videoAssetUrl(assetId, true)).toBe(`/api/video/assets/${assetId}?download=true`);
  });
  it("rejects mismatched progress and unsafe identifiers before using them", async () => {
    respond({ ...completed, totalSentences: 2 });
    await expect(getVideoJob(jobId, 1)).rejects.toThrow(/invalid video progress/);
    respond({ ...completed, assetId: "../private-file" });
    await expect(getVideoJob(jobId, 1)).rejects.toThrow(/invalid video progress/);
    const fetchMock = respond(completed);
    await expect(createVideoJob([{ ...sentences[0], assetId: "../private-file" }], binding)).rejects.toThrow(/current generated audio/);
    await expect(createVideoJob(sentences, binding, "../private-file")).rejects.toThrow(/valid local asset/);
    await expect(createVideoJob([{ ...sentences[0], illustrationAssetId: "../private-file" }], binding)).rejects.toThrow(/valid local asset/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(() => videoAssetUrl("../private-file")).toThrow(/identifier/);
  });
  it("reports missing session state and renderer failures without displaying raw details", async () => {
    respond({ detail: "private process stderr" }, 404);
    await expect(getVideoJob(jobId, 1)).rejects.toMatchObject({ status: 404 });
    respond({ detail: "secret configuration" }, 500);
    await expect(createVideoJob(sentences, binding)).rejects.toThrow(/could not be confirmed/);
  });
  it("requires a valid frozen speech binding and maps stale settings safely", async () => {
    const fetchMock = respond(completed);
    await expect(createVideoJob(sentences, { ...binding, configurationFingerprint: "stale" })).rejects.toThrow(/supported speech voice/);
    expect(fetchMock).not.toHaveBeenCalled();
    respond({ detail: "secret diagnostics" }, 409);
    await expect(createVideoJob(sentences, binding)).rejects.toThrow(/selected speech settings/);
    respond({ detail: "secret diagnostics" }, 422);
    await expect(createVideoJob(sentences, binding)).rejects.toThrow(/selected voice or speech configuration/);
  });
});
