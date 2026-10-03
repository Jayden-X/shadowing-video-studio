import { afterEach, describe, expect, it, vi } from "vitest";

import { getBackendHealth, getTextProviders, prepareText, TextApiError } from "./api";
import { MAX_PROPOSAL_SENTENCES, MAX_SENTENCE_LENGTH, MAX_SOURCE_LENGTH } from "./domain/sentences";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

const providerResponse = {
  providers: [
    { id: "deepseek", label: "DeepSeek", available: true, reason: null },
    { id: "codex", label: "Codex CLI", available: false, reason: "CLI unavailable" },
  ],
};

const proposalResponse = {
  provider: "codex",
  sourceText: "Source dialogue.",
  sentences: ["First sentence.", "Second sentence."],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getBackendHealth", () => {
  it("returns the backend status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getBackendHealth()).resolves.toEqual({ status: "ok" });
  });

  it("throws on a non-success response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 503 })));

    await expect(getBackendHealth()).rejects.toThrow("503");
  });
});

describe("getTextProviders", () => {
  it("validates provider availability, forwards the signal and uses safe local labels and reasons", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ providers: providerResponse.providers.map((provider) => ({
      ...provider, label: "private label", reason: "private path and credential",
    })) }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const providers = await getTextProviders(controller.signal);
    expect(fetchMock).toHaveBeenCalledWith("/api/text/providers", { signal: controller.signal });
    expect(providers).toEqual([
      { id: "deepseek", label: "DeepSeek", available: true, reason: null },
      { id: "codex", label: "Codex CLI", available: false,
        reason: "Codex CLI is unavailable. Check its local installation, login, and service configuration." },
    ]);
    expect(JSON.stringify(providers)).not.toContain("private");
  });

  it.each([
    null,
    { providers: [] },
    { providers: [providerResponse.providers[0]] },
    { providers: [providerResponse.providers[0], providerResponse.providers[0]] },
    { providers: [...providerResponse.providers, providerResponse.providers[0]] },
    { ...providerResponse, extra: true },
    { providers: [{ ...providerResponse.providers[0], id: "other" }, providerResponse.providers[1]] },
    { providers: [{ ...providerResponse.providers[0], available: "yes" }, providerResponse.providers[1]] },
    { providers: [{ ...providerResponse.providers[0], label: "" }, providerResponse.providers[1]] },
    { providers: [{ ...providerResponse.providers[0], label: "x".repeat(81) }, providerResponse.providers[1]] },
    { providers: [{ ...providerResponse.providers[0], reason: {} }, providerResponse.providers[1]] },
    { providers: [{ ...providerResponse.providers[0], reason: "x".repeat(501) }, providerResponse.providers[1]] },
    { providers: [{ ...providerResponse.providers[0], token: "secret" }, providerResponse.providers[1]] },
  ])("rejects malformed provider availability %#", async (value) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(value)));
    await expect(getTextProviders()).rejects.toThrow("invalid provider availability");
  });
});

describe("prepareText", () => {
  it("sends the exact source snapshot and validates the proposal without applying or trimming it", async () => {
    const sourceText = "  Original.\r\nNew line.  ";
    const fetchMock = vi.fn(async () => jsonResponse({ provider: "codex", sourceText, sentences: ["  Proposed sentence.  "] }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await expect(prepareText("codex", sourceText, controller.signal)).resolves.toEqual({
      provider: "codex", sourceText, sentences: ["  Proposed sentence.  "],
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/text/prepare", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: "codex", sourceText }), signal: controller.signal,
    });
  });

  it("accepts the bounded sentence-count, sentence-length and source-length limits", async () => {
    const sourceText = "a".repeat(MAX_SOURCE_LENGTH);
    const sentences = ["a".repeat(MAX_SENTENCE_LENGTH), ...Array.from({ length: MAX_PROPOSAL_SENTENCES - 1 }, () => "Sentence.")];
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ provider: "deepseek", sourceText, sentences })));
    await expect(prepareText("deepseek", sourceText)).resolves.toEqual({ provider: "deepseek", sourceText, sentences });
  });

  it("accepts well-formed emoji up to the UTF-16 source and sentence limits", async () => {
    const sourceText = "😀".repeat(MAX_SOURCE_LENGTH / 2);
    const sentences = ["👋".repeat(MAX_SENTENCE_LENGTH / 2)];
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ provider: "codex", sourceText, sentences })));
    await expect(prepareText("codex", sourceText)).resolves.toEqual({ provider: "codex", sourceText, sentences });
  });

  it.each([
    null,
    [],
    { ...proposalResponse, provider: "deepseek" },
    { ...proposalResponse, provider: "unsupported" },
    { ...proposalResponse, sourceText: "Different source." },
    { ...proposalResponse, sentences: [] },
    { ...proposalResponse, sentences: ["   "] },
    { ...proposalResponse, sentences: [null] },
    { ...proposalResponse, sentences: [42] },
    { ...proposalResponse, sentences: ["\ud800"] },
    { ...proposalResponse, sentences: ["\udc00"] },
    { ...proposalResponse, sentences: ["valid", { text: "invalid", id: "provider-id" }] },
    { ...proposalResponse, sentences: "First sentence." },
    { ...proposalResponse, sentences: ["a".repeat(MAX_SENTENCE_LENGTH + 1)] },
    { ...proposalResponse, sentences: Array.from({ length: MAX_PROPOSAL_SENTENCES + 1 }, () => "Sentence.") },
    { ...proposalResponse, extra: true },
    { sourceText: proposalResponse.sourceText, sentences: proposalResponse.sentences },
  ])("rejects malformed, mismatched or oversized proposals %#", async (value) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(value)));
    await expect(prepareText("codex", proposalResponse.sourceText)).rejects.toThrow("invalid sentence proposal");
  });

  it.each(["", " \n\t ", "a".repeat(MAX_SOURCE_LENGTH + 1)])("rejects invalid source input before any request %#", async (source) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(prepareText("codex", source)).rejects.toBeInstanceOf(TextApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["before \ud800 after", "before \udc00 after"])("rejects isolated Unicode surrogates before any request %#", async (source) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(prepareText("codex", source)).rejects.toThrow("invalid Unicode");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [400, "dialogue or provider is invalid"],
    [422, "dialogue or provider is invalid"],
    [413, "dialogue is too long"],
    [409, "provider is busy"],
    [429, "provider is busy"],
    [503, "provider is unavailable"],
    [504, "preparation timed out"],
    [502, "could not return a valid proposal"],
    [500, "could not complete this request"],
  ])("maps HTTP %s to a safe error without exposing or retrying provider details", async (status, message) => {
    const fetchMock = vi.fn(async () => jsonResponse({ detail: "secret token and raw provider stderr" }, Number(status)));
    vi.stubGlobal("fetch", fetchMock);
    await expect(prepareText("codex", proposalResponse.sourceText)).rejects.toThrow(String(message));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("handles malformed JSON with a safe error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("private token: malformed json", { status: 200 })));
    await expect(prepareText("codex", proposalResponse.sourceText)).rejects.toThrow("invalid response");
  });

  it("handles network failures without exposing their message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("private process command or token"); }));
    await expect(prepareText("codex", proposalResponse.sourceText)).rejects.toThrow("local service is unavailable");
  });

  it("forwards abort and does not turn cancellation into a provider error", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn(async () => {
      controller.abort();
      throw new Error("private abort cause");
    }));
    await expect(prepareText("codex", proposalResponse.sourceText, controller.signal)).rejects.toHaveProperty("name", "AbortError");
  });
});
