import { useEffect, useState } from "react";
import type { SentenceId } from "./domain/sentences";

const STORAGE_KEY = "shadowing-video-studio.visual-selections.v1";
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

export function loadVisualSelections(): VisualSelections {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === null ? emptySelections() : parseVisualSelections(JSON.parse(raw) as unknown);
  } catch {
    return emptySelections();
  }
}

function persistVisualSelections(selections: VisualSelections): boolean {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, ...selections }));
    return true;
  } catch {
    return false;
  }
}

export function useVisualSelections() {
  const [selections, setSelections] = useState(loadVisualSelections);
  const [storageWarning, setStorageWarning] = useState("");

  useEffect(() => {
    setStorageWarning(persistVisualSelections(selections)
      ? ""
      : "The browser could not save image selections. They will remain only until this tab closes.");
  }, [selections]);

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
    clearSentenceIllustrations,
    removeSentenceIllustration,
  };
}
