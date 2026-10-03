import { afterEach, describe, expect, it, vi } from "vitest";

import { getBackendHealth } from "./api";

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
