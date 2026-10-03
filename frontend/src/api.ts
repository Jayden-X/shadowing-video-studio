import {
  isWellFormedText,
  MAX_PROPOSAL_SENTENCES,
  MAX_SENTENCE_LENGTH,
  MAX_SOURCE_LENGTH,
} from "./domain/sentences";

export type HealthResponse = { status: string };
export type TextProviderId = "deepseek" | "codex";
export type TextProvider = {
  id: TextProviderId;
  label: string;
  available: boolean;
  reason: string | null;
};
export type TextProposal = {
  provider: TextProviderId;
  sourceText: string;
  sentences: string[];
};

export class TextApiError extends Error {}

const providerLabels: Record<TextProviderId, string> = {
  deepseek: "DeepSeek",
  codex: "Codex CLI",
};
const unavailableReasons: Record<TextProviderId, string> = {
  deepseek: "DeepSeek is unavailable. Check the local service's provider configuration.",
  codex: "Codex CLI is unavailable. Check its local installation, login, and service configuration.",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isProviderId(value: unknown): value is TextProviderId {
  return value === "deepseek" || value === "codex";
}

function isValidSentence(value: unknown): value is string {
  return typeof value === "string" && !!value.trim() && value.length <= MAX_SENTENCE_LENGTH && isWellFormedText(value);
}

function responseError(status: number): TextApiError {
  if (status === 400 || status === 422) {
    return new TextApiError("The dialogue or provider is invalid. Check your input and try again.");
  }
  if (status === 413) {
    return new TextApiError(`The dialogue is too long. Use at most ${MAX_SOURCE_LENGTH.toLocaleString("en-US")} characters.`);
  }
  if (status === 409 || status === 429) {
    return new TextApiError("The provider is busy. Wait before preparing again.");
  }
  if (status === 503) {
    return new TextApiError("The selected provider is unavailable. Check its local configuration.");
  }
  if (status === 504) {
    return new TextApiError("AI preparation timed out. Your source and current edits are preserved.");
  }
  if (status === 502) {
    return new TextApiError("The provider could not return a valid proposal. Your source and current edits are preserved.");
  }
  return new TextApiError("The local service could not complete this request. Your source and current edits are preserved.");
}

async function requestJson(url: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for the request.", "AbortError");
    throw new TextApiError("The local service is unavailable. Manual editing still works.");
  }
  if (!response.ok) throw responseError(response.status);
  try {
    return await response.json();
  } catch {
    if (init.signal?.aborted) throw new DOMException("Stopped waiting for the request.", "AbortError");
    throw new TextApiError("The local service returned an invalid response. Your source and current edits are preserved.");
  }
}

export async function getBackendHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error(`Backend health check failed: ${response.status}`);
  const value: unknown = await response.json();
  if (!isRecord(value) || typeof value.status !== "string") throw new Error("Invalid backend health response.");
  return { status: value.status };
}

export async function getTextProviders(signal?: AbortSignal): Promise<TextProvider[]> {
  const value = await requestJson("/api/text/providers", { signal });
  const invalid = () => new TextApiError("The local service returned invalid provider availability. Manual editing still works.");
  if (!isRecord(value) || !hasExactKeys(value, ["providers"]) || !Array.isArray(value.providers) || value.providers.length !== 2) {
    throw invalid();
  }
  const providers: TextProvider[] = [];
  const items: unknown[] = value.providers;
  for (const item of items) {
    if (!isRecord(item) || !hasExactKeys(item, ["id", "label", "available", "reason"]) || !isProviderId(item.id)
      || typeof item.label !== "string" || !item.label.trim() || item.label.length > 80
      || typeof item.available !== "boolean" || (item.reason !== null && typeof item.reason !== "string")
      || (typeof item.reason === "string" && item.reason.length > 500)
      || providers.some((provider) => provider.id === item.id)) {
      throw invalid();
    }
    providers.push({
      id: item.id,
      label: providerLabels[item.id],
      available: item.available,
      reason: item.available ? null : unavailableReasons[item.id],
    });
  }
  return providers;
}

export async function prepareText(
  provider: TextProviderId,
  sourceText: string,
  signal?: AbortSignal,
): Promise<TextProposal> {
  if (!isProviderId(provider)) throw new TextApiError("Choose a supported AI provider.");
  if (!sourceText.trim()) throw new TextApiError("Enter dialogue before preparing sentences.");
  if (sourceText.length > MAX_SOURCE_LENGTH) throw responseError(413);
  if (!isWellFormedText(sourceText)) throw new TextApiError("The dialogue contains invalid Unicode. Replace the affected characters before preparing.");
  const value = await requestJson("/api/text/prepare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, sourceText }),
    signal,
  });
  if (!isRecord(value) || !hasExactKeys(value, ["provider", "sourceText", "sentences"])
    || value.provider !== provider || value.sourceText !== sourceText
    || !Array.isArray(value.sentences)) {
    throw new TextApiError("The local service returned an invalid sentence proposal. Your source and current edits are preserved.");
  }
  const sentences: unknown[] = value.sentences;
  if (sentences.length === 0 || sentences.length > MAX_PROPOSAL_SENTENCES || !sentences.every(isValidSentence)) {
    throw new TextApiError("The local service returned an invalid sentence proposal. Your source and current edits are preserved.");
  }
  return { provider, sourceText, sentences: [...sentences] };
}
