import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { createProjectApiTestServer, TEST_PROJECT_ID } from "./projectApiTestServer";
import type { VisualAsset } from "./visualApi";

const speechAssetId = "b".repeat(32);
const backgroundId = "c".repeat(32);
const existingIllustrationId = "d".repeat(32);
const uploadedIllustrationId = "e".repeat(32);
const exportId = "f".repeat(32);
const speechBinding = { voice: "Aiden", configurationFingerprint: "a".repeat(64) };
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
  window.localStorage.removeItem("shadowing-video-studio.project-cache.v1");
});

describe("visual asset workflow", () => {
  it("uploads and selects images, preserves sentence bindings through split/reorder, freezes them for export, and protects state on upload failure and merge", async () => {
    let registeredIllustration: VisualAsset | null = null;
    let failUpload = false;
    let submittedVideo: { voice: string; configurationFingerprint: string; backgroundAssetId?: string | null;
      sentences: { id: string; text: string; assetId: string; illustrationAssetId?: string }[] } | null = null;
    const projectServer = createProjectApiTestServer();
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const storageResponse = projectServer.handleStorage(url, init);
      if (storageResponse) return storageResponse;
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
      if (url === "/api/speech/capabilities") return json({ available: true, reason: null, defaultVoice: "Aiden", model: "Qwen3-TTS", language: "English",
        voices: [{ id: "Aiden", label: "Aiden", configurationFingerprint: speechBinding.configurationFingerprint }] });
      if (url === "/api/video/status") return json({ available: true, reason: null });
      const projectSpeech = await projectServer.submitSpeech(url, init, (sentences) => json({
        id: "a".repeat(32), status: "completed", error: null, ...speechBinding,
        sentences: sentences.map((item) => ({ ...item, ...speechBinding, status: "ready", assetId: speechAssetId,
          durationSeconds: 1.5, error: null, reused: false })),
      }, 202));
      if (projectSpeech) return projectSpeech;
      const projectVideo = await projectServer.submitVideo(url, init, (sentences) => {
        const command = JSON.parse(init?.body as string) as { snapshot: { backgroundAssetId: string | null; voice: string }; configurationFingerprint: string };
        submittedVideo = { voice: command.snapshot.voice, configurationFingerprint: command.configurationFingerprint,
          backgroundAssetId: command.snapshot.backgroundAssetId,
          sentences: sentences.map(({ id, text, assetId, illustrationAssetId }) => ({ id, text, assetId,
            ...(illustrationAssetId ? { illustrationAssetId } : {}) })) };
        return json({ id: "1".repeat(32), status: "completed", completedSentences: sentences.length,
          totalSentences: sentences.length, assetId: exportId, durationSeconds: 20, error: null }, 202);
      });
      if (projectVideo) return projectVideo;
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
      ...speechBinding,
      backgroundAssetId: backgroundId,
      sentences: [
        { id: "sentence-001", text: "Hello", assetId: speechAssetId, illustrationAssetId: uploadedIllustrationId },
        { id: "sentence-002", text: "Next.", assetId: speechAssetId, illustrationAssetId: existingIllustrationId },
        { id: "sentence-003", text: "world.", assetId: speechAssetId },
      ],
    });
    expect(screen.getAllByRole("link", { name: "Download MP4" }).length).toBeGreaterThan(0);

    const createRequest = fetchMock.mock.calls.find(([url, request]) => url === "/api/projects" && request?.method === "POST");
    const savedProject = JSON.parse(createRequest?.[1]?.body as string) as { snapshot: { backgroundAssetId: string; illustrationsBySentence: Record<string, string> } };
    expect(savedProject.snapshot.backgroundAssetId).toBe(backgroundId);
    expect(savedProject.snapshot.illustrationsBySentence).toEqual({
      "sentence-001": uploadedIllustrationId, "sentence-002": existingIllustrationId,
    });
    expect(window.localStorage.getItem("shadowing-video-studio.visual-selections.v1")).toBeNull();

    failUpload = true;
    const rejectedFile = new File(["another fixture"], "Retry after refresh.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload image for Illustration for sentence 1"), { target: { files: [rejectedFile] } });
    await screen.findByText(/Choose a valid PNG, JPEG, or WebP image/);
    expect(imageChoice("Illustration for sentence 1").value).toBe(uploadedIllustrationId);
    expect(sentence(1).value).toBe("Hello");
    expect(document.querySelectorAll("audio")).toHaveLength(3);
    expect(screen.getAllByRole("link", { name: "Download MP4" }).length).toBeGreaterThan(0);
    expect(screen.queryByText(/private workspace path/)).toBeNull();

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(button("Merge sentence 2 with previous"));
    expect(confirm).toHaveBeenCalledOnce();
    expect(sentence(2).value).toBe("Next.");
    confirm.mockReturnValue(true);
    fireEvent.click(button("Merge sentence 2 with previous"));
    await waitFor(() => expect(sentence(1).value).toBe("Hello Next."));
    expect(imageChoice("Illustration for sentence 1").value).toBe(uploadedIllustrationId);
    fireEvent.click(button("Save"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === `/api/projects/${TEST_PROJECT_ID}` && request?.method === "PUT")).toBe(true));

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
    registeredIllustration = { ...registeredIllustration, available: true, reason: null };
    render(<App />);
    await screen.findByRole("option", { name: /Morning background\.png/ });
    expect(imageChoice("Background image").value).toBe("");
    fireEvent.change(imageChoice("Open project"), { target: { value: TEST_PROJECT_ID } });
    await waitFor(() => expect(imageChoice("Background image").value).toBe(backgroundId));
    expect(imageChoice("Background image").value).toBe(backgroundId);
    expect(imageChoice("Illustration for sentence 1").value).toBe(uploadedIllustrationId);
    expect(imageChoice("Illustration for sentence 2").value).toBe("");
  });
});
