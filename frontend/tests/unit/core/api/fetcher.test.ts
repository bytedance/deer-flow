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

  test("falls through to refresh_token flow when EHM re-authentication fails", async () => {
    vi.stubGlobal("document", {
      cookie: "ehm_token=ehm-jwt-token; csrf_token=test-csrf-token",
    });

    const fetchMock = vi
      .fn()
      // Original request → 401
      .mockResolvedValueOnce(makeResponse(401, { detail: { code: "not_authenticated" } }))
      // EHM re-authenticate → 401 (fails)
      .mockResolvedValueOnce(makeResponse(401, { detail: { code: "invalid_credentials" } }))
      // Refresh token → 200 (succeeds)
      .mockResolvedValueOnce(makeResponse(200, { message: "Token refreshed" }))
      // Retry original request → 200
      .mockResolvedValueOnce(makeResponse(200, { ok: true }));

    vi.stubGlobal("fetch", fetchMock);

    const response = await fetchWithAuth("/api/template-marketplace/abc/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_visibility: "private" }),
    });

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(4);

    // Call 0: original request
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/template-marketplace/abc/install");
    // Call 1: EHM re-authenticate (fails)
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/auth/ins-base/authenticate");
    // Call 2: refresh token fallback
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/v1/auth/refresh");
    // Call 3: retry original request
    expect(fetchMock.mock.calls[3]?.[0]).toBe("/api/template-marketplace/abc/install");
  });

  test("falls through to redirect when both EHM re-auth and refresh fail", async () => {
    vi.stubGlobal("document", {
      cookie: "ehm_token=ehm-jwt-token; csrf_token=test-csrf-token",
    });

    const setTimeoutMock = vi.fn();
    vi.stubGlobal("window", {
      location: {
        href: "http://localhost:2026/workspace",
        pathname: "/workspace",
      },
      setTimeout: setTimeoutMock,
    });

    const fetchMock = vi
      .fn()
      // Original request → 401
      .mockResolvedValueOnce(makeResponse(401, { detail: { code: "not_authenticated" } }))
      // EHM re-authenticate → fails (network error)
      .mockRejectedValueOnce(new Error("network error"))
      // Refresh token → 401 (also fails)
      .mockResolvedValueOnce(makeResponse(401, { detail: { code: "token_expired" } }));

    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchWithAuth("/api/some-endpoint", { method: "GET" }),
    ).rejects.toThrow("Unauthorized");

    // Should have scheduled a redirect
    expect(setTimeoutMock).toHaveBeenCalledTimes(1);
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
