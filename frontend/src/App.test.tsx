import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => jsonResponse(
    url === "/api/projects" ? { projects: [] }
      : url === "/api/text/providers" ? { providers: availableProviders }
      : url === "/api/visuals/status" ? visualStatus
      : url === "/api/visuals/assets" ? { assets: [] }
      : { status: "ok" },
  )));
});

const availableProviders = [
  { id: "deepseek", label: "DeepSeek", available: true, reason: null },
  { id: "codex", label: "Codex CLI", available: true, reason: null },
];
const visualStatus = { available: true, reason: null, maxUploadBytes: 10 * 1024 * 1024, formats: ["image/png", "image/jpeg", "image/webp"] };

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function mockPreparation(result: (init: RequestInit | undefined) => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/projects") return jsonResponse({ projects: [] });
    if (url === "/api/text/providers") return jsonResponse({ providers: availableProviders });
    if (url === "/api/text/prepare") return result(init);
    if (url === "/api/visuals/status") return jsonResponse(visualStatus);
    if (url === "/api/visuals/assets") return jsonResponse({ assets: [] });
    return jsonResponse({ status: "ok" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function selectAi(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("radio", { name: "AI-assisted" }));
  await screen.findByRole("option", { name: "Codex CLI" });
  await user.selectOptions(screen.getByRole("combobox", { name: "AI provider" }), "codex");
}

function sentence(position: number): HTMLTextAreaElement {
  return screen.getByRole("textbox", { name: `Sentence ${position}` }) as HTMLTextAreaElement;
}

function button(name: string): HTMLButtonElement {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

async function prepare(user: ReturnType<typeof userEvent.setup>, source: string) {
  await user.type(screen.getByRole("textbox", { name: "Source dialogue" }), source);
  await user.click(button("Prepare sentences"));
}

describe("manual sentence editor", () => {
  it("prepares ordered sentences and keeps the source snapshot separate from edits and the source draft", async () => {
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Hello there. How are you?");
    expect(sentence(1).value).toBe("Hello there.");
    expect(sentence(2).value).toBe("How are you?");

    const originalId = sentence(1).id;
    await user.clear(sentence(1));
    await user.type(sentence(1), "Welcome.");
    const source = screen.getByRole("textbox", { name: "Source dialogue" });
    await user.clear(source);
    await user.type(source, "A different draft.");
    await user.click(screen.getByText("Original source snapshot"));

    expect(screen.getByText("Hello there. How are you?").tagName).toBe("PRE");
    expect(sentence(1).value).toBe("Welcome.");
    expect(sentence(1).id).toBe(originalId);
  });

  it("supports editing, adding, cursor splitting, reordering, merging and deleting", async () => {
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Alpha beta. Gamma.");
    const originalId = sentence(1).id;
    await user.clear(sentence(1));
    await user.type(sentence(1), "Alpha beta changed.");
    sentence(1).focus();
    sentence(1).setSelectionRange(5, 5);
    await user.click(button("Split sentence 1 at cursor"));
    expect(sentence(1).value).toBe("Alpha");
    expect(sentence(1).id).toBe(originalId);
    expect(sentence(2).value).toBe("beta changed.");

    await user.click(button("Add after sentence 2"));
    await user.type(sentence(3), "Inserted.");
    const insertedId = sentence(3).id;
    await user.click(button("Move sentence 3 up"));
    expect(sentence(2).value).toBe("Inserted.");
    expect(sentence(2).id).toBe(insertedId);
    await user.click(button("Move sentence 2 down"));
    expect(sentence(3).value).toBe("Inserted.");
    await user.click(button("Merge sentence 3 with previous"));
    expect(sentence(2).value).toBe("beta changed. Inserted.");
    await user.click(button("Delete sentence 2"));
    expect(sentence(1).value).toBe("Alpha");
    expect(sentence(2).value).toBe("Gamma.");
    expect(screen.queryByRole("textbox", { name: "Sentence 3" })).toBeNull();
  });

  it("requires confirmation before replacing edits, preserves the draft on cancel, and replaces only after confirmation", async () => {
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Original text.");
    await user.clear(sentence(1));
    await user.type(sentence(1), "My edited sentence.");
    const source = screen.getByRole("textbox", { name: "Source dialogue" }) as HTMLTextAreaElement;
    await user.clear(source);
    await user.type(source, "Replacement. Next.");
    await user.click(button("Prepare sentences"));

    expect(screen.getByRole("alertdialog").textContent).toContain("Replace the current sentence list?");
    expect(sentence(1).value).toBe("My edited sentence.");
    expect(source.disabled).toBe(true);
    expect(document.activeElement).toBe(button("Cancel"));
    await user.click(button("Cancel"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(sentence(1).value).toBe("My edited sentence.");
    expect(source.value).toBe("Replacement. Next.");
    expect(document.activeElement).toBe(button("Prepare sentences"));
    await user.click(screen.getByText("Original source snapshot"));
    expect(screen.getByText("Original text.").tagName).toBe("PRE");

    await user.click(button("Prepare sentences"));
    await user.click(button("Replace and prepare"));
    expect(sentence(1).value).toBe("Replacement.");
    expect(sentence(2).value).toBe("Next.");
    expect(screen.getByText("Replacement. Next.", { selector: "pre" }).tagName).toBe("PRE");
    expect(screen.queryByText("Original text.")).toBeNull();
  });

  it("allows cancelling replacement with Escape", async () => {
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Keep this.");
    await user.click(button("Prepare sentences"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(sentence(1).value).toBe("Keep this.");
    expect(document.activeElement).toBe(button("Prepare sentences"));
  });

  it("protects manually added sentences when preparing source for the first time", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(button("Add sentence"));
    await user.type(sentence(1), "Manually written.");
    await user.type(screen.getByRole("textbox", { name: "Source dialogue" }), "Pasted source.");
    await user.click(button("Prepare sentences"));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(sentence(1).value).toBe("Manually written.");
    await user.click(button("Cancel"));
    expect(sentence(1).value).toBe("Manually written.");
    expect(screen.queryByText("Original source snapshot")).toBeNull();
  });

  it("splits at the retained text cursor using the keyboard", async () => {
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Hello world.");
    sentence(1).focus();
    await user.keyboard("{Home}{ArrowRight}{ArrowRight}{ArrowRight}{ArrowRight}{ArrowRight}");
    expect(sentence(1).selectionStart).toBe(5);
    await user.tab();
    expect(document.activeElement).toBe(button("Split sentence 1 at cursor"));
    await user.keyboard("{Enter}");
    expect(sentence(1).value).toBe("Hello");
    expect(sentence(2).value).toBe("world.");
  });

  it("explains invalid split positions and rejects a text selection without losing text", async () => {
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Hello world.");
    const input = sentence(1);
    for (const offset of [0, input.value.length]) {
      input.focus();
      input.setSelectionRange(offset, offset);
      fireEvent.click(button("Split sentence 1 at cursor"));
      expect(screen.getByText(/Place the cursor between two non-empty parts/)).toBeTruthy();
      expect(sentence(1).value).toBe("Hello world.");
      expect(screen.queryByRole("textbox", { name: "Sentence 2" })).toBeNull();
    }
    input.setSelectionRange(0, 5);
    fireEvent.click(button("Split sentence 1 at cursor"));
    expect(screen.getByText(/Collapse the selection/)).toBeTruthy();
    expect(sentence(1).value).toBe("Hello world.");
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(5);
  });

  it("disables boundary operations and supports keyboard activation", async () => {
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "First. Second.");
    expect(button("Move sentence 1 up").disabled).toBe(true);
    expect(button("Merge sentence 1 with previous").disabled).toBe(true);
    expect(button("Move sentence 2 down").disabled).toBe(true);
    button("Move sentence 2 up").focus();
    await user.keyboard("{Enter}");
    expect(sentence(1).value).toBe("Second.");
    expect(sentence(2).value).toBe("First.");
    button("Delete sentence 2").focus();
    await user.keyboard(" ");
    expect(button("Move sentence 1 up").disabled).toBe(true);
    expect(button("Move sentence 1 down").disabled).toBe(true);
    expect(button("Merge sentence 1 with previous").disabled).toBe(true);
  });

  it("supports an empty list, adding the first sentence and deleting every sentence", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.getByText("Your sentence list starts here")).toBeTruthy();
    expect(button("Prepare sentences").disabled).toBe(true);
    await user.type(screen.getByRole("textbox", { name: "Source dialogue" }), "   ");
    expect(button("Prepare sentences").disabled).toBe(true);
    await user.click(button("Add sentence"));
    await user.type(sentence(1), "A new sentence.");
    await user.click(button("Delete sentence 1"));
    expect(screen.getByText("Your sentence list starts here")).toBeTruthy();
    await user.click(button("Add sentence"));
    expect(sentence(1).value).toBe("");
  });

  it("continues to prepare and edit sentences when the local service is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("Local service unavailable · Editing still works")).toBeTruthy();
    await prepare(user, "Offline editing.");
    await user.type(sentence(1), " Still local.");
    expect(sentence(1).value).toBe("Offline editing. Still local.");
    await user.click(button("Add sentence"));
    expect(sentence(2).value).toBe("");
  });
});

describe("AI-assisted preparation", () => {
  it("requires an explicit mode, provider selection and prepare action, then applies only reviewed output", async () => {
    const sourceText = "  Hello there.\nHow are you?  ";
    const fetchMock = mockPreparation(() => jsonResponse({ provider: "codex", sourceText, sentences: ["  Hello there.  ", "How are you?"] }));
    const user = userEvent.setup();
    render(<App />);
    expect((screen.getByRole("radio", { name: "Manual" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: sourceText } });
    await user.click(screen.getByRole("radio", { name: "AI-assisted" }));
    const provider = screen.getByRole("combobox", { name: "AI provider" }) as HTMLSelectElement;
    expect(provider.value).toBe("");
    expect(button("Prepare AI proposal").disabled).toBe(true);
    await user.selectOptions(provider, "codex");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/text/prepare")).toHaveLength(0);
    await user.click(button("Prepare AI proposal"));
    const proposedList = await screen.findByRole("list", { name: "Proposed sentences" });
    expect(within(proposedList).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["  Hello there.  ", "How are you?"]);
    expect(screen.queryByRole("textbox", { name: "Sentence 1" })).toBeNull();
    expect(screen.queryByText("Original source snapshot")).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/text/prepare")).toHaveLength(1);
    await user.click(button("Apply reviewed sentences"));
    expect(screen.queryByRole("heading", { name: "Review AI proposal" })).toBeNull();
    expect(sentence(1).value).toBe("Hello there.");
    expect(sentence(2).value).toBe("How are you?");
    const sentenceId = sentence(1).id;
    expect(sentenceId).toBe("input-sentence-001");
    await user.type(sentence(1), " Welcome.");
    expect(sentence(1).id).toBe(sentenceId);
    await user.click(button("Move sentence 1 down"));
    expect(sentence(2).id).toBe(sentenceId);
    await user.click(screen.getByText("Original source snapshot"));
    expect(screen.getByText((_, element) => element?.tagName === "PRE" && element.textContent === sourceText)).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Source dialogue" }) as HTMLTextAreaElement).value).toBe(sourceText);
  });

  it("preserves existing edits and the draft when discarding a proposal or when a provider fails", async () => {
    const draft = "  New draft.  ";
    let fail = false;
    const fetchMock = mockPreparation(() => fail
      ? jsonResponse({ detail: "private token and raw provider stderr" }, 502)
      : jsonResponse({ provider: "codex", sourceText: draft, sentences: ["New proposal."] }));
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Original source.");
    await user.clear(sentence(1));
    await user.type(sentence(1), "My correction.");
    const originalId = sentence(1).id;
    fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: draft } });
    await selectAi(user);
    await user.click(button("Prepare AI proposal"));
    await screen.findByRole("heading", { name: "Review AI proposal" });
    expect(sentence(1).value).toBe("My correction.");
    await user.click(button("Discard proposal"));
    expect(sentence(1).value).toBe("My correction.");
    expect(sentence(1).id).toBe(originalId);
    expect((screen.getByRole("textbox", { name: "Source dialogue" }) as HTMLTextAreaElement).value).toBe(draft);
    fail = true;
    await user.click(button("Prepare AI proposal"));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "The provider could not return a valid proposal. Your source and current edits are preserved.");
    expect(screen.queryByText(/private token/)).toBeNull();
    expect(sentence(1).value).toBe("My correction.");
    expect(sentence(1).id).toBe(originalId);
    expect((screen.getByRole("textbox", { name: "Source dialogue" }) as HTMLTextAreaElement).value).toBe(draft);
    await user.click(screen.getByText("Original source snapshot"));
    expect(screen.getByText("Original source.", { selector: "pre" })).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/text/prepare")).toHaveLength(2);
  });

  it("requires replacement confirmation and returns to the proposal when confirmation is cancelled", async () => {
    const fetchMock = mockPreparation(() => jsonResponse({ provider: "codex", sourceText: "Replacement.", sentences: ["AI replacement."] }));
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Keep my source.");
    await user.type(sentence(1), " Edited.");
    fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: "Replacement." } });
    await selectAi(user);
    await user.click(button("Prepare AI proposal"));
    await screen.findByRole("heading", { name: "Review AI proposal" });
    await user.click(button("Apply reviewed sentences"));
    expect(screen.getByRole("alertdialog").textContent).toContain("replaces all current sentence edits");
    expect(sentence(1).value).toBe("Keep my source. Edited.");
    expect(sentence(1).disabled).toBe(true);
    expect(document.activeElement).toBe(button("Cancel"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(button("Apply reviewed sentences"));
    expect(sentence(1).value).toBe("Keep my source. Edited.");
    expect(screen.getByRole("heading", { name: "Review AI proposal" })).toBeTruthy();
    await user.click(button("Apply reviewed sentences"));
    await user.click(button("Replace and apply"));
    expect(sentence(1).value).toBe("AI replacement.");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await user.click(screen.getByText("Original source snapshot"));
    expect(screen.getByText("Replacement.", { selector: "pre" })).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/text/prepare")).toHaveLength(1);
  });

  it("explains unavailable providers safely and leaves manual preparation usable", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => jsonResponse(url === "/api/text/providers"
      ? { providers: availableProviders.map((provider) => ({ ...provider, available: false, reason: "secret token" })) }
      : url === "/api/visuals/status" ? visualStatus
      : url === "/api/visuals/assets" ? { assets: [] }
      : { status: "ok" })));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("radio", { name: "AI-assisted" }));
    expect(await screen.findByText(/Codex CLI is unavailable/)).toBeTruthy();
    expect(screen.getByText(/DeepSeek is unavailable/)).toBeTruthy();
    expect(screen.queryByText(/secret token/)).toBeNull();
    expect((screen.getByRole("option", { name: "Codex CLI · Unavailable" }) as HTMLOptionElement).disabled).toBe(true);
    expect(button("Prepare AI proposal").disabled).toBe(true);
    await user.click(screen.getByRole("radio", { name: "Manual" }));
    await prepare(user, "Still editable.");
    expect(sentence(1).value).toBe("Still editable.");
  });

  it("locks editing while pending, aborts waiting and ignores a late response before another request", async () => {
    let resolveFirst!: (response: Response) => void;
    let firstSignal: AbortSignal | null | undefined;
    let calls = 0;
    mockPreparation((init) => {
      calls += 1;
      if (calls === 1) {
        firstSignal = init?.signal;
        return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      }
      return jsonResponse({ provider: "codex", sourceText: "Second draft.", sentences: ["Current proposal."] });
    });
    const user = userEvent.setup();
    render(<App />);
    await prepare(user, "Original.");
    await selectAi(user);
    await user.click(button("Prepare AI proposal"));
    expect(sentence(1).disabled).toBe(true);
    expect(button("Add sentence").disabled).toBe(true);
    expect(button("Delete sentence 1").disabled).toBe(true);
    expect((screen.getByRole("textbox", { name: "Source dialogue" }) as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByRole("combobox", { name: "AI provider" }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("radio", { name: "Manual" }) as HTMLInputElement).matches(":disabled")).toBe(true);
    await user.click(button("Stop waiting"));
    expect(firstSignal?.aborted).toBe(true);
    expect(sentence(1).disabled).toBe(false);
    expect(sentence(1).value).toBe("Original.");
    fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: "Second draft." } });
    await user.click(button("Prepare AI proposal"));
    await screen.findByText("Current proposal.");
    await act(async () => { resolveFirst(jsonResponse({ provider: "codex", sourceText: "Original.", sentences: ["Stale response."] })); });
    expect(screen.queryByText("Stale response.")).toBeNull();
    expect(screen.getByText("Current proposal.")).toBeTruthy();
    expect(sentence(1).value).toBe("Original.");
  });

  it("aborts pending requests when unmounted", async () => {
    let requestSignal: AbortSignal | null | undefined;
    mockPreparation((init) => {
      requestSignal = init?.signal;
      return new Promise<Response>(() => {});
    });
    const user = userEvent.setup();
    const view = render(<App />);
    await user.type(screen.getByRole("textbox", { name: "Source dialogue" }), "Source.");
    await selectAi(user);
    await user.click(button("Prepare AI proposal"));
    view.unmount();
    expect(requestSignal?.aborted).toBe(true);
  });

  it("preserves oversized input and prevents a provider call", async () => {
    const fetchMock = mockPreparation(() => jsonResponse({}));
    const user = userEvent.setup();
    render(<App />);
    await selectAi(user);
    const source = screen.getByRole("textbox", { name: "Source dialogue" }) as HTMLTextAreaElement;
    fireEvent.change(source, { target: { value: "a".repeat(20_001) } });
    expect(source.value).toHaveLength(20_001);
    expect(screen.getByRole("alert").textContent).toContain("full draft is preserved");
    expect(button("Prepare AI proposal").disabled).toBe(true);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/text/prepare")).toHaveLength(0);
  });

  it("bounds waiting with a timeout and preserves source and edits", async () => {
    let requestSignal: AbortSignal | null | undefined;
    mockPreparation((init) => {
      requestSignal = init?.signal;
      return new Promise<Response>(() => {});
    });
    vi.useFakeTimers();
    render(<App />);
    await act(async () => {});
    fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: "Timed source." } });
    fireEvent.click(button("Prepare sentences"));
    fireEvent.click(screen.getByRole("radio", { name: "AI-assisted" }));
    fireEvent.change(screen.getByRole("combobox", { name: "AI provider" }), { target: { value: "codex" } });
    fireEvent.click(button("Prepare AI proposal"));
    await act(async () => { vi.advanceTimersByTime(120_000); });
    expect(requestSignal?.aborted).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("timed out");
    expect(sentence(1).value).toBe("Timed source.");
    expect(sentence(1).disabled).toBe(false);
    expect((screen.getByRole("textbox", { name: "Source dialogue" }) as HTMLTextAreaElement).value).toBe("Timed source.");
    expect(screen.queryByRole("heading", { name: "Review AI proposal" })).toBeNull();
  });
});
