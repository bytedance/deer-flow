import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { fetch as fetchWithAuth } from "@/core/api/fetcher";

function makeResponse(status = 200, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

describe("fetchWithAuth refresh flow", () => {
  beforeEach(() => {
    vi.stubGlobal("document", {
      cookie: "csrf_token=test-csrf-token",
    });
    vi.stubGlobal("window", {
      location: {
        href: "http://localhost:2026/workspace",
        pathname: "/workspace",
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("sends the CSRF header when refreshing an expired session", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeResponse(401))
      .mockResolvedValueOnce(makeResponse(200, { message: "Token refreshed" }))
      .mockResolvedValueOnce(makeResponse(200, { ok: true }));

    vi.stubGlobal("fetch", fetchMock);

    const response = await fetchWithAuth("/api/threads/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 10 }),
    });

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    const [, refreshInit] = fetchMock.mock.calls[1]!;
    const refreshHeaders = new Headers(refreshInit?.headers);

    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/auth/refresh");
    expect(refreshInit?.method).toBe("POST");
    expect(refreshInit?.credentials).toBe("include");
    expect(refreshHeaders.get("X-CSRF-Token")).toBe("test-csrf-token");
  });
});
