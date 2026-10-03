import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubHealthyBackend() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

describe("manual sentence editor", () => {
  it("prepares editable sentences while preserving the source snapshot", async () => {
    stubHealthyBackend();
    const user = userEvent.setup();
    render(<App />);

    const source = screen.getByRole("textbox", { name: "Source dialogue" });
    await user.type(source, "Hello there. How are you?");
    await user.click(screen.getByRole("button", { name: "Prepare sentences" }));

    expect((screen.getByRole("textbox", { name: "Sentence 1" }) as HTMLTextAreaElement).value).toBe(
      "Hello there.",
    );
    expect((screen.getByRole("textbox", { name: "Sentence 2" }) as HTMLTextAreaElement).value).toBe(
      "How are you?",
    );

    await user.click(screen.getByText("Original source snapshot"));
    expect(screen.getByText("Hello there. How are you?")).toBeTruthy();
  });

  it("supports add, edit, split, reorder, merge, and delete through the UI", async () => {
    stubHealthyBackend();
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox", { name: "Source dialogue" }), "Alpha beta. Gamma.");
    await user.click(screen.getByRole("button", { name: "Prepare sentences" }));

    const firstSentence = screen.getByRole("textbox", { name: "Sentence 1" }) as HTMLTextAreaElement;
    await user.clear(firstSentence);
    await user.type(firstSentence, "Alpha beta.");

    firstSentence.focus();
    firstSentence.setSelectionRange(5, 5);
    fireEvent.click(screen.getByRole("button", { name: "Split sentence 1 at cursor" }));

    expect((screen.getByRole("textbox", { name: "Sentence 1" }) as HTMLTextAreaElement).value).toBe(
      "Alpha",
    );
    expect((screen.getByRole("textbox", { name: "Sentence 2" }) as HTMLTextAreaElement).value).toBe(
      "beta.",
    );

    await user.click(screen.getByRole("button", { name: "Add after sentence 2" }));
    const thirdCard = screen.getByTestId("sentence-card-3");
    const thirdText = within(thirdCard).getByRole("textbox");
    await user.type(thirdText, "Inserted.");

    await user.click(screen.getByRole("button", { name: "Move sentence 3 up" }));
    expect(
      (screen.getByRole("textbox", { name: "Sentence 2" }) as HTMLTextAreaElement).value,
    ).toBe("Inserted.");

    await user.click(screen.getByRole("button", { name: "Merge sentence 2 with previous" }));
    expect(
      (screen.getByRole("textbox", { name: "Sentence 1" }) as HTMLTextAreaElement).value,
    ).toBe("Alpha Inserted.");

    await user.click(screen.getByRole("button", { name: "Delete sentence 1" }));
    expect(screen.queryByDisplayValue("Alpha Inserted.")).toBeNull();
  });
});
