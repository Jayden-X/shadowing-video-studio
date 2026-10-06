import { afterEach, describe, expect, it, vi } from "vitest";
import { createProjectVideoJob, createVideoJob, getProjectVideoJob, getVideoJob, validateProjectVideoAttemptJob,
  videoAssetUrl } from "./videoApi";

const jobId = "a".repeat(32);
const assetId = "b".repeat(32);
const sentences = [{ id: "sentence-001", text: "Hello.", assetId: "c".repeat(32) }];
const binding = { voice: "Aiden", configurationFingerprint: "f".repeat(64) };
const completed = { id: jobId, status: "completed", completedSentences: 1, totalSentences: 1,
  assetId, durationSeconds: 6.5, error: null };
const projectId = "d".repeat(32);
const documentId = "e".repeat(32);
const submissionToken = "f".repeat(32);
const projectRevision = 3;
const projectSnapshot = { version: 1 as const, documentId, sourceDraft: "Hello.",
  document: { sourceText: "Hello.", sentences: [{ id: sentences[0].id, text: sentences[0].text }], nextSequence: 2 },
  hasPrepared: true, mode: "manual" as const, voice: binding.voice, backgroundAssetId: null, illustrationsBySentence: {} };
const projectCommand = { projectId, documentId, expectedRevision: projectRevision, name: "Video project",
  snapshot: projectSnapshot, submissionToken };
const projectExpectation = { projectId, documentId, submissionToken, revision: { exact: projectRevision } } as const;
const projectJob = { ...completed, projectId, documentId, projectRevision, submissionToken };
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
  it("uses one strict Project Video Job schema for submission, polling and attempt recovery", async () => {
    const expected = { ...completed, projectId, documentId, projectRevision, submissionToken };
    const fetchMock = respond(projectJob, 202);
    expect(await createProjectVideoJob(sentences, binding, projectCommand)).toEqual(expected);
    expect(fetchMock).toHaveBeenCalledWith(`/api/projects/${projectId}/video`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operationToken: submissionToken, expectedRevision: projectRevision, name: "Video project",
        snapshot: projectSnapshot, configurationFingerprint: binding.configurationFingerprint,
        audioAssetIds: { "sentence-001": sentences[0].assetId } }),
      signal: undefined,
    });

    respond(projectJob);
    expect(await getProjectVideoJob(jobId, 1, projectExpectation)).toEqual(expected);
    expect(validateProjectVideoAttemptJob(projectJob, 1, projectExpectation, jobId)).toEqual(expected);

    respond(projectJob);
    await expect(getVideoJob(jobId, 1)).rejects.toThrow(/invalid video progress/);
  });
  it("rejects Project Video Jobs with mismatched project identity or revision", async () => {
    for (const value of [
      { ...projectJob, projectId: "a".repeat(32) },
      { ...projectJob, documentId: "a".repeat(32) },
      { ...projectJob, submissionToken: "a".repeat(32) },
      { ...projectJob, extra: true },
    ]) {
      respond(value, 202);
      await expect(createProjectVideoJob(sentences, binding, projectCommand)).rejects.toThrow(/invalid video progress/);
      respond(value);
      await expect(getProjectVideoJob(jobId, 1, projectExpectation)).rejects.toThrow(/invalid video progress/);
      expect(() => validateProjectVideoAttemptJob(value, 1, projectExpectation, jobId)).toThrow(/invalid video progress/);
    }
    const wrongRevision = { ...projectJob, projectRevision: projectRevision + 1 };
    respond(wrongRevision);
    await expect(getProjectVideoJob(jobId, 1, projectExpectation)).rejects.toThrow(/invalid video progress/);
    expect(() => validateProjectVideoAttemptJob(wrongRevision, 1, projectExpectation, jobId)).toThrow(/invalid video progress/);
    respond({ ...projectJob, projectRevision: projectRevision - 1 }, 202);
    await expect(createProjectVideoJob(sentences, binding, projectCommand)).rejects.toThrow(/invalid video progress/);
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
