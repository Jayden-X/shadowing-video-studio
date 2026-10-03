import { afterEach, describe, expect, it, vi } from "vitest";
import { createVideoJob, getVideoJob, videoAssetUrl } from "./videoApi";

const jobId = "a".repeat(32);
const assetId = "b".repeat(32);
const sentences = [{ id: "sentence-001", text: "Hello.", assetId: "c".repeat(32) }];
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
    expect(await createVideoJob(sentences, controller.signal)).toEqual(completed);
    expect(fetchMock).toHaveBeenCalledWith("/api/video/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sentences }), signal: controller.signal,
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
    await expect(createVideoJob([{ ...sentences[0], assetId: "../private-file" }])).rejects.toThrow(/current generated audio/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(() => videoAssetUrl("../private-file")).toThrow(/identifier/);
  });
  it("reports missing session state and renderer failures without displaying raw details", async () => {
    respond({ detail: "private process stderr" }, 404);
    await expect(getVideoJob(jobId, 1)).rejects.toMatchObject({ status: 404 });
    respond({ detail: "secret configuration" }, 500);
    await expect(createVideoJob(sentences)).rejects.toThrow(/could not be confirmed/);
  });
});
