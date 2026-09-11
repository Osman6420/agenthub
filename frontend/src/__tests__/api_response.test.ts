import { afterEach, describe, expect, it, vi } from "vitest";

import { BuilderApi } from "../api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("builder API response envelopes", () => {
  it("turns an HTML error page into a stable status-bearing API error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<!doctype html><title>Not found</title>", {
      status: 404,
      headers: { "Content-Type": "text/html" },
    })));

    const promise = new BuilderApi("/console/api/builder/").listDrafts();

    await expect(promise).rejects.toMatchObject({
      code: "unexpected_response",
      status: 404,
      message: "Sunucu isteği JSON olmayan bir yanıtla reddetti (HTTP 404).",
    });
  });

  it("preserves a structured JSON API error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      error: { code: "stale_revision", message: "Taslak değişti" },
    }), { status: 409, headers: { "Content-Type": "application/json" } })));

    await expect(new BuilderApi("/console/api/builder/").listDrafts()).rejects.toMatchObject({
      code: "stale_revision",
      status: 409,
      message: "Taslak değişti",
    });
  });
});
