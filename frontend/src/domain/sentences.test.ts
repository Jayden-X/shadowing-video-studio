import { describe, expect, it } from "vitest";

import {
  createSentenceDocument,
  createSentenceDocumentFromProposal,
  deleteSentence,
  insertSentenceAfter,
  isWellFormedText,
  mergeWithPrevious,
  moveSentence,
  splitSentence,
  splitSourceText,
  updateSentenceText,
} from "./sentences";

describe("reviewed sentence proposals", () => {
  it("accepts complete emoji pairs and rejects isolated Unicode surrogates", () => {
    expect(isWellFormedText("Hello 👋. 中文。" )).toBe(true);
    for (const value of ["\uD800", "\uDC00", "a\uD800b", "\uD800\uD800", "\uDC00\uDC00"]) {
      expect(isWellFormedText(value)).toBe(false);
      expect(() => createSentenceDocumentFromProposal(value, ["Sentence."])).toThrow("Unicode");
      expect(() => createSentenceDocumentFromProposal("Source.", [value])).toThrow();
    }
    const document = createSentenceDocumentFromProposal("Hello 👋.", [" Hi 👋. "]);
    expect(document.sourceText).toBe("Hello 👋.");
    expect(document.sentences[0].text).toBe("Hi 👋.");
  });

  it("counts supplementary characters as two UTF-16 units before trimming", () => {
    expect(() => createSentenceDocumentFromProposal("👋".repeat(10_001), ["Hi."])).toThrow();
    expect(() => createSentenceDocumentFromProposal("Source.", ["👋".repeat(2_001)])).toThrow();
    expect(() => createSentenceDocumentFromProposal("Source.", [" " + "x".repeat(4_000)])).toThrow();
    expect(createSentenceDocumentFromProposal("👋".repeat(10_000), ["👋".repeat(2_000)]).sentences).toHaveLength(1);
  });

  it("creates application identities and preserves source and provider-independent ordering", () => {
    const source = "  Original dialogue.\r\nKeep it exactly. ";
    const proposal = [" A revised sentence. ", "Another sentence?"];
    const document = createSentenceDocumentFromProposal(source, proposal);

    expect(document).toEqual({
      sourceText: source,
      sentences: [
        { id: "sentence-001", text: "A revised sentence." },
        { id: "sentence-002", text: "Another sentence?" },
      ],
      nextSequence: 3,
    });
    expect(proposal).toEqual([" A revised sentence. ", "Another sentence?"]);
    expect(createSentenceDocumentFromProposal(source, proposal)).toEqual(document);
    const edited = updateSentenceText(document, "sentence-001", "My correction.");
    expect(edited.sourceText).toBe(source);
    expect(edited.sentences[0].id).toBe("sentence-001");
    expect(insertSentenceAfter(edited, null).sentences[2].id).toBe("sentence-003");
  });

  it("rejects empty and oversized proposals before creating a canonical document", () => {
    expect(() => createSentenceDocumentFromProposal("Source.", [])).toThrow("1–500");
    expect(() => createSentenceDocumentFromProposal("Source.", ["  "])).toThrow("1–4,000");
    expect(() => createSentenceDocumentFromProposal("Source.", ["x".repeat(4_001)])).toThrow("1–4,000");
    expect(() => createSentenceDocumentFromProposal("Source.", Array(501).fill("Sentence."))).toThrow("1–500");
    expect(() => createSentenceDocumentFromProposal(" ", ["Sentence."])).toThrow("1–20,000");
    expect(() => createSentenceDocumentFromProposal("x".repeat(20_001), ["Sentence."])).toThrow("1–20,000");
  });
});

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

  it("preserves punctuation and closing quotes in the editable list", () => {
    expect(splitSourceText('...Hello! "Are you ready?" Yes...')).toEqual([
      "...",
      "Hello!",
      '"Are you ready?"',
      "Yes...",
    ]);
    expect(splitSourceText("?!")).toEqual(["?!"]);
  });

  it("handles Windows line endings and text without final punctuation", () => {
    expect(splitSourceText(" First line\r\n\rSecond line\n Last line ")).toEqual([
      "First line",
      "Second line",
      "Last line",
    ]);
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

  it("does not reuse deleted identities and can add to an empty document", () => {
    const original = createSentenceDocument("One.");
    const emptied = deleteSentence(original, "sentence-001");
    const added = insertSentenceAfter(emptied, null, "New sentence.");

    expect(added.sentences).toEqual([{ id: "sentence-002", text: "New sentence." }]);
    expect(insertSentenceAfter(createSentenceDocument(""), null).sentences).toEqual([
      { id: "sentence-001", text: "" },
    ]);
  });

  it("preserves the exact source and the input document across all editing operations", () => {
    const source = "  One two.\r\nThree.  ";
    const original = createSentenceDocument(source);
    const initialSnapshot = structuredClone(original);
    const edited = updateSentenceText(original, "sentence-001", "First second.");
    const split = splitSentence(edited, "sentence-001", 5);
    const inserted = insertSentenceAfter(split, "sentence-003", "Inserted.");
    const reordered = moveSentence(inserted, "sentence-002", "up");
    const merged = mergeWithPrevious(reordered, "sentence-002");
    const deleted = deleteSentence(merged, "sentence-004");

    for (const document of [edited, split, inserted, reordered, merged, deleted]) {
      expect(document.sourceText).toBe(source);
    }
    expect(original).toEqual(initialSnapshot);
    expect(deleted.nextSequence).toBe(5);
  });

  it("returns the same document for moves and merges at list boundaries", () => {
    const document = createSentenceDocument("One. Two.");

    expect(moveSentence(document, "sentence-001", "up")).toBe(document);
    expect(moveSentence(document, "sentence-002", "down")).toBe(document);
    expect(mergeWithPrevious(document, "sentence-001")).toBe(document);
    expect(splitSentence(document, "sentence-001", -10)).toBe(document);
    expect(splitSentence(document, "sentence-001", 100)).toBe(document);
  });

  it("rejects invalid targets without mutating the document", () => {
    const document = createSentenceDocument("One.");
    const snapshot = structuredClone(document);

    expect(() => insertSentenceAfter(document, "missing")).toThrow("Sentence not found");
    expect(() => splitSentence(document, "missing", 1)).toThrow("Sentence not found");
    expect(() => moveSentence(document, "missing", "up")).toThrow("Sentence not found");
    expect(document).toEqual(snapshot);
  });
});
