import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { VisualAsset } from "./visualApi";

const speechAssetId = "b".repeat(32);
const backgroundId = "c".repeat(32);
const existingIllustrationId = "d".repeat(32);
const uploadedIllustrationId = "e".repeat(32);
const exportId = "f".repeat(32);
const visualStatus = {
  available: true,
  reason: null,
  maxUploadBytes: 10 * 1024 * 1024,
  formats: ["image/png", "image/jpeg", "image/webp"],
};
const initialAssets = [
  { id: backgroundId, kind: "background", name: "Morning background.png", mimeType: "image/png", width: 1920, height: 1080, sizeBytes: 128, available: true, reason: null },
  { id: existingIllustrationId, kind: "illustration", name: "Existing illustration.png", mimeType: "image/png", width: 640, height: 640, sizeBytes: 96, available: true, reason: null },
];
const availableProviders = [
  { id: "deepseek", label: "DeepSeek", available: true, reason: null },
  { id: "codex", label: "Codex CLI", available: true, reason: null },
];

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}
function button(name: string): HTMLButtonElement { return screen.getByRole("button", { name }) as HTMLButtonElement; }
function sentence(position: number): HTMLTextAreaElement { return screen.getByRole("textbox", { name: `Sentence ${position}` }) as HTMLTextAreaElement; }
function imageChoice(name: string): HTMLSelectElement { return screen.getByRole("combobox", { name }) as HTMLSelectElement; }

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.removeItem("shadowing-video-studio.visual-selections.v1");
});

describe("visual asset workflow", () => {
  it("uploads and selects images, preserves sentence bindings through split/reorder, freezes them for export, and protects state on upload failure and merge", async () => {
    let registeredIllustration: VisualAsset | null = null;
    let failUpload = false;
    let submittedVideo: { backgroundAssetId?: string; sentences: { id: string; text: string; assetId: string; illustrationAssetId?: string }[] } | null = null;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/health") return json({ status: "ok" });
      if (url === "/api/text/providers") return json({ providers: availableProviders });
      if (url === "/api/visuals/status") return json(visualStatus);
      if (url === "/api/visuals/assets") return json({ assets: registeredIllustration ? [...initialAssets, registeredIllustration] : initialAssets });
      if (url.startsWith("/api/visuals/assets?") && init?.method === "POST") {
        if (failUpload) return json({ detail: "private workspace path" }, 422);
        const file = init.body as File;
        registeredIllustration = {
          id: uploadedIllustrationId, kind: "illustration", name: file.name, mimeType: "image/png",
          width: 800, height: 600, sizeBytes: file.size, available: true, reason: null,
        };
        return json(registeredIllustration, 201);
      }
      if (url === "/api/speech/status") return json({ available: true, reason: null, voice: "Aiden", model: "Qwen3-TTS", backend: "cpu" });
      if (url === "/api/video/status") return json({ available: true, reason: null });
      if (url === "/api/speech/jobs") {
        const body = JSON.parse(init?.body as string) as { sentences: { id: string; text: string }[] };
        return json({ id: "a".repeat(32), status: "completed", error: null, sentences: body.sentences.map((item) => ({
          ...item, status: "ready", assetId: speechAssetId, durationSeconds: 1.5, error: null, reused: false,
        })) }, 202);
      }
      if (url === "/api/video/jobs") {
        submittedVideo = JSON.parse(init?.body as string) as typeof submittedVideo;
        return json({ id: "1".repeat(32), status: "completed", completedSentences: submittedVideo!.sentences.length,
          totalSentences: submittedVideo!.sentences.length, assetId: exportId, durationSeconds: 20, error: null }, 202);
      }
      return json({ status: "ok" });
    });
    vi.stubGlobal("fetch", fetchMock);
    const app = render(<App />);

    await screen.findByRole("option", { name: /Morning background\.png/ });
    fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: "Hello world. Next." } });
    fireEvent.click(button("Prepare sentences"));
    fireEvent.change(imageChoice("Background image"), { target: { value: backgroundId } });
    fireEvent.change(imageChoice("Illustration for sentence 2"), { target: { value: existingIllustrationId } });

    const newImage = new File(["small fixture image"], "Uploaded illustration.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload image for Illustration for sentence 1"), { target: { files: [newImage] } });
    await waitFor(() => expect(imageChoice("Illustration for sentence 1").value).toBe(uploadedIllustrationId));

    sentence(1).focus();
    sentence(1).setSelectionRange(6, 6);
    fireEvent.click(button("Split sentence 1 at cursor"));
    expect(sentence(1).value).toBe("Hello");
    expect(sentence(2).value).toBe("world.");
    expect(imageChoice("Illustration for sentence 1").value).toBe(uploadedIllustrationId);
    expect(imageChoice("Illustration for sentence 2").value).toBe("");
    expect(screen.getByText(/illustration stays with the first part/).textContent).toContain("new sentence has no illustration");

    fireEvent.click(button("Move sentence 3 up"));
    expect(sentence(2).value).toBe("Next.");
    expect(imageChoice("Illustration for sentence 2").value).toBe(existingIllustrationId);
    await act(async () => { fireEvent.click(button("Generate speech")); });
    await waitFor(() => expect(document.querySelectorAll("audio").length).toBe(3));
    await act(async () => { fireEvent.click(button("Generate video")); });

    expect(submittedVideo).toEqual({
      backgroundAssetId: backgroundId,
      sentences: [
        { id: "sentence-001", text: "Hello", assetId: speechAssetId, illustrationAssetId: uploadedIllustrationId },
        { id: "sentence-002", text: "Next.", assetId: speechAssetId, illustrationAssetId: existingIllustrationId },
        { id: "sentence-003", text: "world.", assetId: speechAssetId },
      ],
    });
    expect(screen.getByRole("link", { name: "Download MP4" })).toBeTruthy();

    const stored = JSON.parse(window.localStorage.getItem("shadowing-video-studio.visual-selections.v1") ?? "null") as Record<string, unknown>;
    expect(stored).toEqual({ version: 1, backgroundAssetId: backgroundId,
      illustrationsBySentence: { "sentence-001": uploadedIllustrationId, "sentence-002": existingIllustrationId } });
    expect(JSON.stringify(stored)).not.toContain("Uploaded illustration.png");

    failUpload = true;
    const rejectedFile = new File(["another fixture"], "Retry after refresh.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload image for Illustration for sentence 1"), { target: { files: [rejectedFile] } });
    await screen.findByText(/Choose a valid PNG, JPEG, or WebP image/);
    expect(imageChoice("Illustration for sentence 1").value).toBe(uploadedIllustrationId);
    expect(sentence(1).value).toBe("Hello");
    expect(document.querySelectorAll("audio")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Download MP4" })).toBeTruthy();
    expect(screen.queryByText(/private workspace path/)).toBeNull();

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(button("Merge sentence 2 with previous"));
    expect(confirm).toHaveBeenCalledOnce();
    expect(sentence(2).value).toBe("Next.");
    confirm.mockReturnValue(true);
    fireEvent.click(button("Merge sentence 2 with previous"));
    await waitFor(() => expect(sentence(1).value).toBe("Hello Next."));
    expect(imageChoice("Illustration for sentence 1").value).toBe(uploadedIllustrationId);
    const afterMerge = JSON.parse(window.localStorage.getItem("shadowing-video-studio.visual-selections.v1") ?? "null") as {
      illustrationsBySentence: Record<string, string>;
    };
    expect(afterMerge.illustrationsBySentence).toEqual({ "sentence-001": uploadedIllustrationId });

    registeredIllustration = {
      id: uploadedIllustrationId, kind: "illustration", name: "Uploaded illustration.png", mimeType: "image/png",
      width: 800, height: 600, sizeBytes: newImage.size, available: false,
      reason: "Image file is missing. Re-upload it or choose another image.",
    };
    fireEvent.click(button("Refresh image library"));
    await waitFor(() => expect(screen.getAllByText(/Image file is missing/)).toHaveLength(2));
    expect(button("Generate video").disabled).toBe(true);

    registeredIllustration = { ...registeredIllustration, available: true, reason: null };
    fireEvent.click(button("Refresh image library"));
    await waitFor(() => expect(screen.queryByText(/Image file is missing/)).toBeNull());

    app.unmount();
    registeredIllustration = null;
    render(<App />);
    await screen.findByRole("option", { name: /Morning background\.png/ });
    const persisted = JSON.parse(window.localStorage.getItem("shadowing-video-studio.visual-selections.v1") ?? "null") as {
      backgroundAssetId: string;
      illustrationsBySentence: Record<string, string>;
    };
    expect(persisted.backgroundAssetId).toBe(backgroundId);
    expect(persisted.illustrationsBySentence).toEqual({ "sentence-001": uploadedIllustrationId });
    fireEvent.change(screen.getByRole("textbox", { name: "Source dialogue" }), { target: { value: "Hello world. Next." } });
    fireEvent.click(button("Prepare sentences"));
    expect(imageChoice("Background image").value).toBe(backgroundId);
    expect(imageChoice("Illustration for sentence 1").value).toBe("");
  });
});
