import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })));
});

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
