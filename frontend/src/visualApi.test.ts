import { afterEach, describe, expect, it, vi } from "vitest";
import { getVisualAssets, getVisualStatus, uploadVisualAsset, visualAssetUrl } from "./visualApi";

const asset = {
  id: "a".repeat(32),
  kind: "background",
  name: "Lake & trees.png",
  mimeType: "image/png",
  width: 1920,
  height: 1080,
  sizeBytes: 8,
  available: true,
  reason: null,
};
const status = {
  available: true,
  reason: null,
  maxUploadBytes: 10 * 1024 * 1024,
  formats: ["image/png", "image/jpeg", "image/webp"],
};

function jsonResponse(value: unknown, statusCode = 200): Response {
  return new Response(JSON.stringify(value), { status: statusCode, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("visual library API boundary", () => {
  it("loads validated availability and library records and builds opaque preview URLs", async () => {
    const fetchMock = vi.fn(async (url: string) => url.endsWith("/status")
      ? jsonResponse(status)
      : jsonResponse({ assets: [asset] }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getVisualStatus(controller.signal)).resolves.toEqual({ ...status, formats: [...status.formats] });
    await expect(getVisualAssets(controller.signal)).resolves.toEqual([asset]);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/visuals/status", { signal: controller.signal });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/visuals/assets", { signal: controller.signal });
    expect(visualAssetUrl(asset.id)).toBe(`/api/visuals/assets/${asset.id}`);
    expect(() => visualAssetUrl("../private-file")).toThrow(/identifier/);
  });

  it("uploads raw image bytes with the selected visual role and encoded display name", async () => {
    const file = new File(["image bytes"], "Lake & trees.png", { type: "image/png" });
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ ...asset, sizeBytes: file.size }, 201));
    vi.stubGlobal("fetch", fetchMock);

    await expect(uploadVisualAsset(file, "background")).resolves.toEqual({ ...asset, sizeBytes: file.size });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/visuals/assets?kind=background&name=Lake%20%26%20trees.png");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("image/png");
    expect(init?.body).toBe(file);
  });

  it("rejects malformed library data and maps upload failures to safe guidance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ assets: [{ ...asset, id: "../private-file" }] })));
    await expect(getVisualAssets()).rejects.toThrow(/invalid image library data/);

    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ detail: "private filesystem path" }, 422));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["bad"], "bad.png", { type: "image/png" });
    await expect(uploadVisualAsset(file, "illustration")).rejects.toThrow("Choose a valid PNG, JPEG, or WebP");
    expect(fetchMock.mock.calls[0][0]).toContain("kind=illustration");
    expect(fetchMock.mock.calls[0][0]).not.toContain("private filesystem path");
  });
});
