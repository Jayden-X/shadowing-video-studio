import { describe, expect, it } from "vitest";
import { currentSentenceAudio, getCompleteSpeechSelection, jobMatchesSnapshot, selectJobAudio, speechInputProblem, type SpeechJob } from "./speech";

const sentence = { id: "sentence-001", text: "Hello." };
const readyJob: SpeechJob = {
  id: "a".repeat(32), status: "completed", error: null,
  sentences: [{ ...sentence, status: "ready", assetId: "b".repeat(32), durationSeconds: 1.5, error: null, reused: false }],
};

describe("speech selection", () => {
  it("matches the entire ordered frozen snapshot", () => {
    expect(jobMatchesSnapshot(readyJob, [sentence])).toBe(true);
    expect(jobMatchesSnapshot(readyJob, [{ ...sentence, text: "Changed." }])).toBe(false);
    expect(jobMatchesSnapshot(readyJob, [{ ...sentence, id: "another" }])).toBe(false);
    expect(jobMatchesSnapshot(readyJob, [sentence, { id: "other", text: "Next." }])).toBe(false);
  });
  it("preserves successful selection across pending and failed attempts", () => {
    const original = selectJobAudio({}, readyJob);
    const failed: SpeechJob = { ...readyJob, status: "failed", error: "Failed.", sentences: [{ ...readyJob.sentences[0], status: "failed", assetId: null, durationSeconds: null, error: "Failed." }] };
    expect(selectJobAudio(original, failed)).toEqual(original);
    expect(original[sentence.id].assetId).toBe("b".repeat(32));
    const regenerated = selectJobAudio(original, { ...readyJob, sentences: [{ ...readyJob.sentences[0], assetId: "c".repeat(32) }] });
    expect(regenerated[sentence.id].assetId).toBe("c".repeat(32));
    expect(original[sentence.id].assetId).toBe("b".repeat(32));
  });
  it("invalidates edited text and incomplete lists for preview and video", () => {
    const selection = selectJobAudio({}, readyJob);
    expect(currentSentenceAudio(sentence, selection)?.assetId).toBe("b".repeat(32));
    expect(currentSentenceAudio({ ...sentence, text: "Hello. " }, selection)).toBeNull();
    expect(getCompleteSpeechSelection([sentence], selection)).toEqual([selection[sentence.id]]);
    expect(getCompleteSpeechSelection([{ ...sentence, text: "Different." }], selection)).toBeNull();
    expect(getCompleteSpeechSelection([sentence, { id: "other", text: "Next." }], selection)).toBeNull();
    expect(getCompleteSpeechSelection([], selection)).toBeNull();
  });
  it("returns audio in current sentence order after reordering", () => {
    const next = { id: "sentence-002", text: "Next." };
    const selection = selectJobAudio({}, { ...readyJob, sentences: [...readyJob.sentences, { ...readyJob.sentences[0], ...next, assetId: "c".repeat(32) }] });
    expect(getCompleteSpeechSelection([next, sentence], selection)?.map((audio) => audio.id)).toEqual([next.id, sentence.id]);
  });
  it("treats opaque IDs as own keys without prototype collisions", () => {
    const unusual = { ...sentence, id: "__proto__" };
    const selection = selectJobAudio({}, { ...readyJob, sentences: [{ ...readyJob.sentences[0], ...unusual }] });
    expect(Object.getPrototypeOf(selection)).toBeNull();
    expect(currentSentenceAudio(unusual, selection)?.assetId).toBe("b".repeat(32));
    expect(currentSentenceAudio({ ...sentence, id: "constructor" }, {})).toBeNull();
  });
  it.each([
    [], [{ ...sentence, text: " " }], [{ ...sentence, text: "x".repeat(4_001) }],
    [{ ...sentence, text: "\ud800" }], [sentence, sentence], [{ ...sentence, id: "" }],
    [{ ...sentence, id: " " }], [{ ...sentence, id: "\ud800" }],
    Array.from({ length: 101 }, (_, index) => ({ id: String(index), text: "Hello." })),
    Array.from({ length: 6 }, (_, index) => ({ id: String(index), text: "x".repeat(4_000) })),
  ].map((sentences) => [sentences]))("rejects invalid input %#", (sentences) => {
    expect(speechInputProblem(sentences)).not.toBeNull();
  });
  it("accepts valid limits and complete surrogate pairs", () => {
    expect(speechInputProblem(Array.from({ length: 100 }, (_, index) => ({ id: String(index), text: "Hello." })))).toBeNull();
    expect(speechInputProblem([{ ...sentence, text: "😀".repeat(2_000) }])).toBeNull();
  });
});
