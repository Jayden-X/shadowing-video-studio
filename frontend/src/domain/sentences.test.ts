import { describe, expect, it } from "vitest";

import {
  createSentenceDocument,
  deleteSentence,
  insertSentenceAfter,
  mergeWithPrevious,
  moveSentence,
  splitSentence,
  splitSourceText,
  updateSentenceText,
} from "./sentences";

describe("splitSourceText", () => {
  it("splits by punctuation and line boundaries deterministically", () => {
    expect(splitSourceText("Hello there. How are you?\nI am fine!")).toEqual([
      "Hello there.",
      "How are you?",
      "I am fine!",
    ]);
  });

  it("ignores blank input", () => {
    expect(splitSourceText("  \n\n ")).toEqual([]);
  });
});

describe("sentence document operations", () => {
  it("preserves the original source text", () => {
    const source = "First sentence. Second sentence.";
    const document = createSentenceDocument(source);

    expect(document.sourceText).toBe(source);
    expect(document.sentences.map((sentence) => sentence.text)).toEqual([
      "First sentence.",
      "Second sentence.",
    ]);
  });

  it("edits text without changing sentence identity", () => {
    const document = createSentenceDocument("Hello.");

    const updated = updateSentenceText(document, "sentence-001", "Hello there.");

    expect(updated.sentences[0]).toEqual({
      id: "sentence-001",
      text: "Hello there.",
    });
  });

  it("adds a sentence with a stable new identity", () => {
    const document = createSentenceDocument("One. Two.");

    const updated = insertSentenceAfter(document, "sentence-001", "Inserted.");

    expect(updated.sentences.map((sentence) => sentence.id)).toEqual([
      "sentence-001",
      "sentence-003",
      "sentence-002",
    ]);
    expect(updated.nextSequence).toBe(4);
  });

  it("deletes a sentence", () => {
    const document = createSentenceDocument("One. Two.");

    const updated = deleteSentence(document, "sentence-001");

    expect(updated.sentences.map((sentence) => sentence.text)).toEqual(["Two."]);
  });

  it("splits at the requested character offset and retains the left identity", () => {
    const document = createSentenceDocument("Hello world.");

    const updated = splitSentence(document, "sentence-001", 5);

    expect(updated.sentences).toEqual([
      { id: "sentence-001", text: "Hello" },
      { id: "sentence-002", text: "world." },
    ]);
  });

  it("does not split when either side would be empty", () => {
    const document = createSentenceDocument("Hello.");

    expect(splitSentence(document, "sentence-001", 0)).toBe(document);
    expect(splitSentence(document, "sentence-001", 6)).toBe(document);
  });

  it("merges with the previous sentence and keeps the previous identity", () => {
    const document = createSentenceDocument("One. Two.");

    const updated = mergeWithPrevious(document, "sentence-002");

    expect(updated.sentences).toEqual([{ id: "sentence-001", text: "One. Two." }]);
  });

  it("moves sentences without changing their identities", () => {
    const document = createSentenceDocument("One. Two. Three.");

    const movedUp = moveSentence(document, "sentence-003", "up");
    const movedDown = moveSentence(movedUp, "sentence-001", "down");

    expect(movedDown.sentences.map((sentence) => sentence.id)).toEqual([
      "sentence-003",
      "sentence-001",
      "sentence-002",
    ]);
  });
});
