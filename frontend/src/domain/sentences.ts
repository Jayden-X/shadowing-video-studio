export type SentenceId = string;

export type SentenceItem = {
  id: SentenceId;
  text: string;
};

export type SentenceDocument = {
  sourceText: string;
  sentences: SentenceItem[];
  nextSequence: number;
};

export type MoveDirection = "up" | "down";

export const MAX_SOURCE_LENGTH = 20_000;
export const MAX_PROPOSAL_SENTENCES = 500;
export const MAX_SENTENCE_LENGTH = 4_000;

export function isWellFormedText(value: string): boolean {
  // Limits use UTF-16 code units on both API sides; complete surrogate pairs are valid.
  return !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value);
}

function createSentenceId(sequence: number): SentenceId {
  return `sentence-${String(sequence).padStart(3, "0")}`;
}

export function splitSourceText(sourceText: string): string[] {
  const normalized = sourceText.replace(/\r\n?/g, "\n").trim();

  if (!normalized) {
    return [];
  }

  return normalized
    .split(/\n+/)
    .flatMap((line) => {
      const trimmed = line.trim();

      if (!trimmed) {
        return [];
      }

      // Keep leading/standalone punctuation as editable content too. This is a
      // simple manual-mode heuristic, not linguistic sentence analysis.
      return trimmed.match(/[^.!?]*[.!?]+["'”’)]*|[^.!?]+$/g) ?? [trimmed];
    })
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

export function createSentenceDocument(sourceText: string): SentenceDocument {
  const sentenceTexts = splitSourceText(sourceText);
  const sentences = sentenceTexts.map((text, index) => ({
    id: createSentenceId(index + 1),
    text,
  }));

  return {
    sourceText,
    sentences,
    nextSequence: sentences.length + 1,
  };
}

export function createSentenceDocumentFromProposal(
  sourceText: string,
  sentenceTexts: readonly string[],
): SentenceDocument {
  if (!sourceText.trim() || sourceText.length > MAX_SOURCE_LENGTH) {
    throw new Error("Source dialogue must contain 1–20,000 characters.");
  }
  if (!isWellFormedText(sourceText)) {
    throw new Error("Source dialogue contains invalid Unicode characters.");
  }
  if (sentenceTexts.length === 0 || sentenceTexts.length > MAX_PROPOSAL_SENTENCES) {
    throw new Error("A proposal must contain 1–500 sentences.");
  }

  const sentences = sentenceTexts.map((text, index) => {
    if (!text.trim() || text.length > MAX_SENTENCE_LENGTH || !isWellFormedText(text)) {
      throw new Error("Proposed sentences must contain 1–4,000 characters.");
    }
    return { id: createSentenceId(index + 1), text: text.trim() };
  });

  return { sourceText, sentences, nextSequence: sentences.length + 1 };
}

export function updateSentenceText(
  document: SentenceDocument,
  id: SentenceId,
  text: string,
): SentenceDocument {
  return {
    ...document,
    sentences: document.sentences.map((sentence) =>
      sentence.id === id ? { ...sentence, text } : sentence,
    ),
  };
}

export function insertSentenceAfter(
  document: SentenceDocument,
  afterId: SentenceId | null,
  text = "",
): SentenceDocument {
  const sentence: SentenceItem = {
    id: createSentenceId(document.nextSequence),
    text,
  };

  if (afterId === null) {
    return {
      ...document,
      sentences: [...document.sentences, sentence],
      nextSequence: document.nextSequence + 1,
    };
  }

  const index = document.sentences.findIndex((item) => item.id === afterId);

  if (index < 0) {
    throw new Error(`Sentence not found: ${afterId}`);
  }

  return {
    ...document,
    sentences: [
      ...document.sentences.slice(0, index + 1),
      sentence,
      ...document.sentences.slice(index + 1),
    ],
    nextSequence: document.nextSequence + 1,
  };
}

export function deleteSentence(document: SentenceDocument, id: SentenceId): SentenceDocument {
  return {
    ...document,
    sentences: document.sentences.filter((sentence) => sentence.id !== id),
  };
}

export function splitSentence(
  document: SentenceDocument,
  id: SentenceId,
  offset: number,
): SentenceDocument {
  const index = document.sentences.findIndex((sentence) => sentence.id === id);

  if (index < 0) {
    throw new Error(`Sentence not found: ${id}`);
  }

  const current = document.sentences[index];
  const safeOffset = Math.max(0, Math.min(offset, current.text.length));
  const left = current.text.slice(0, safeOffset).trim();
  const right = current.text.slice(safeOffset).trim();

  if (!left || !right) {
    return document;
  }

  const rightSentence: SentenceItem = {
    id: createSentenceId(document.nextSequence),
    text: right,
  };

  return {
    ...document,
    sentences: [
      ...document.sentences.slice(0, index),
      { ...current, text: left },
      rightSentence,
      ...document.sentences.slice(index + 1),
    ],
    nextSequence: document.nextSequence + 1,
  };
}

export function mergeWithPrevious(
  document: SentenceDocument,
  id: SentenceId,
): SentenceDocument {
  const index = document.sentences.findIndex((sentence) => sentence.id === id);

  if (index <= 0) {
    return document;
  }

  const previous = document.sentences[index - 1];
  const current = document.sentences[index];
  const mergedText = [previous.text.trim(), current.text.trim()].filter(Boolean).join(" ");

  return {
    ...document,
    sentences: [
      ...document.sentences.slice(0, index - 1),
      { ...previous, text: mergedText },
      ...document.sentences.slice(index + 1),
    ],
  };
}

export function moveSentence(
  document: SentenceDocument,
  id: SentenceId,
  direction: MoveDirection,
): SentenceDocument {
  const index = document.sentences.findIndex((sentence) => sentence.id === id);

  if (index < 0) {
    throw new Error(`Sentence not found: ${id}`);
  }

  const targetIndex = direction === "up" ? index - 1 : index + 1;

  if (targetIndex < 0 || targetIndex >= document.sentences.length) {
    return document;
  }

  const sentences = [...document.sentences];
  [sentences[index], sentences[targetIndex]] = [sentences[targetIndex], sentences[index]];

  return {
    ...document,
    sentences,
  };
}
