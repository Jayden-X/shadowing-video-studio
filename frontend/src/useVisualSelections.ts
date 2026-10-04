import { useState } from "react";
import type { SentenceId } from "./domain/sentences";

const assetIdPattern = /^[a-f0-9]{32}$/;
const sentenceIdPattern = /^sentence-\d+$/;

export type VisualSelections = {
  backgroundAssetId: string | null;
  illustrationsBySentence: Record<SentenceId, string>;
};

const emptySelections = (): VisualSelections => ({ backgroundAssetId: null, illustrationsBySentence: {} });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseVisualSelections(value: unknown): VisualSelections {
  if (!isRecord(value) || value.version !== 1 || !Object.hasOwn(value, "backgroundAssetId")
    || !Object.hasOwn(value, "illustrationsBySentence")) return emptySelections();
  const backgroundAssetId = value.backgroundAssetId;
  const rawIllustrations = value.illustrationsBySentence;
  if ((backgroundAssetId !== null && (typeof backgroundAssetId !== "string" || !assetIdPattern.test(backgroundAssetId)))
    || !isRecord(rawIllustrations)) return emptySelections();

  const illustrationsBySentence: Record<SentenceId, string> = {};
  for (const [sentenceId, assetId] of Object.entries(rawIllustrations)) {
    if (!sentenceIdPattern.test(sentenceId) || typeof assetId !== "string" || !assetIdPattern.test(assetId)) {
      return emptySelections();
    }
    illustrationsBySentence[sentenceId] = assetId;
  }
  return { backgroundAssetId, illustrationsBySentence };
}

export function useVisualSelections() {
  // Project state is restored only from the backend snapshot. The prior browser-wide
  // selection cache has no project/document identity and is not safe to apply here.
  const [selections, setSelections] = useState<VisualSelections>(emptySelections);
  const storageWarning = "";

  function setBackgroundAssetId(backgroundAssetId: string | null) {
    setSelections((current) => ({ ...current, backgroundAssetId }));
  }

  function setSentenceIllustration(sentenceId: SentenceId, assetId: string | null) {
    setSelections((current) => {
      const illustrationsBySentence = { ...current.illustrationsBySentence };
      if (assetId === null) delete illustrationsBySentence[sentenceId];
      else illustrationsBySentence[sentenceId] = assetId;
      return { ...current, illustrationsBySentence };
    });
  }

  function clearSentenceIllustrations() {
    setSelections((current) => ({ ...current, illustrationsBySentence: {} }));
  }

  function replaceSelections(next: VisualSelections) {
    setSelections({
      backgroundAssetId: next.backgroundAssetId,
      illustrationsBySentence: { ...next.illustrationsBySentence },
    });
  }

  function removeSentenceIllustration(sentenceId: SentenceId) {
    setSelections((current) => {
      if (!Object.hasOwn(current.illustrationsBySentence, sentenceId)) return current;
      const illustrationsBySentence = { ...current.illustrationsBySentence };
      delete illustrationsBySentence[sentenceId];
      return { ...current, illustrationsBySentence };
    });
  }

  return {
    selections,
    storageWarning,
    setBackgroundAssetId,
    setSentenceIllustration,
    replaceSelections,
    clearSentenceIllustrations,
    removeSentenceIllustration,
  };
}
