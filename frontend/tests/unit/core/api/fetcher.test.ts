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

  test("re-authenticates EHM users and retries the original request after a 401", async () => {
    vi.stubGlobal("document", {
      cookie: "ehm_token=ehm-jwt-token",
    });
    const backendPublishUrl =
      "https://gateway.example.com/api/report-templates/tpl_1/publish";

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeResponse(401, { detail: { code: "not_authenticated" } }))
      .mockResolvedValueOnce(makeResponse(200, { authenticated: true }))
      .mockResolvedValueOnce(makeResponse(200, { ok: true }));

    vi.stubGlobal("fetch", fetchMock);

    const response = await fetchWithAuth(backendPublishUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_current_version: 0 }),
    });

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    const [, authInit] = fetchMock.mock.calls[1]!;
    const authHeaders = new Headers(authInit?.headers);

    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "https://gateway.example.com/api/v1/auth/ins-base/authenticate",
    );
    expect(authInit?.method).toBe("POST");
    expect(authInit?.credentials).toBe("include");
    expect(authHeaders.get("Authorization")).toBe("Bearer ehm-jwt-token");
  });
});
