import { isWellFormedText, MAX_SENTENCE_LENGTH, MAX_SOURCE_LENGTH, type SentenceItem } from "./sentences";

export const MAX_SPEECH_SENTENCES = 100;

export type SpeechAudio = { id: string; text: string; assetId: string; durationSeconds: number; reused: boolean };
export type SpeechSelection = Readonly<Record<string, SpeechAudio>>;
export type SpeechSentence = {
  id: string;
  text: string;
  status: "pending" | "generating" | "ready" | "failed";
  assetId: string | null;
  durationSeconds: number | null;
  error: string | null;
  reused: boolean;
};
export type SpeechJob = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  sentences: SpeechSentence[];
  error: string | null;
};

export function speechInputProblem(sentences: readonly SentenceItem[]): string | null {
  if (sentences.length === 0) return "Prepare and review sentences before generating speech.";
  if (sentences.length > MAX_SPEECH_SENTENCES) return "Use at most 100 sentences for one speech job.";
  const ids = new Set<string>();
  for (const sentence of sentences) {
    if (!sentence.id.trim() || sentence.id.length > 100 || !isWellFormedText(sentence.id) || ids.has(sentence.id)) return "Sentence identifiers are invalid. Prepare the sentence list again.";
    ids.add(sentence.id);
    if (!sentence.text.trim() || sentence.text.length > MAX_SENTENCE_LENGTH || !isWellFormedText(sentence.text)) {
      return "Every sentence needs valid text of 1–4,000 characters before generating speech.";
    }
  }
  if (sentences.reduce((total, sentence) => total + sentence.text.length, 0) > MAX_SOURCE_LENGTH) {
    return "Use at most 20,000 sentence characters for one speech job.";
  }
  return null;
}

export function jobMatchesSnapshot(job: SpeechJob, snapshot: readonly SentenceItem[]): boolean {
  return job.sentences.length === snapshot.length && job.sentences.every((sentence, index) =>
    sentence.id === snapshot[index].id && sentence.text === snapshot[index].text);
}

export function selectJobAudio(selection: SpeechSelection, job: SpeechJob): SpeechSelection {
  const next = Object.assign(Object.create(null) as Record<string, SpeechAudio>, selection);
  for (const sentence of job.sentences) {
    if (sentence.status === "ready" && sentence.assetId !== null && sentence.durationSeconds !== null) {
      next[sentence.id] = {
        id: sentence.id, text: sentence.text, assetId: sentence.assetId,
        durationSeconds: sentence.durationSeconds, reused: sentence.reused,
      };
    }
  }
  return next;
}

export function currentSentenceAudio(sentence: SentenceItem, selection: SpeechSelection): SpeechAudio | null {
  const audio = Object.hasOwn(selection, sentence.id) ? selection[sentence.id] : undefined;
  return audio?.text === sentence.text ? audio : null;
}

// Video rendering consumes this complete ordered mapping, never a stale or partial job.
export function getCompleteSpeechSelection(sentences: readonly SentenceItem[], selection: SpeechSelection): SpeechAudio[] | null {
  if (speechInputProblem(sentences)) return null;
  const audio = sentences.map((sentence) => currentSentenceAudio(sentence, selection));
  return audio.every((item) => item !== null) ? audio : null;
}
