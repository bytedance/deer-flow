import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the token module before importing authFetch
vi.mock("../token", () => ({
  getAccessToken: vi.fn(),
  isTokenExpired: vi.fn(),
  clearAccessToken: vi.fn(),
}));

vi.mock("../api", () => ({
  refreshToken: vi.fn(),
}));

import { refreshToken } from "../api";
import { authFetch } from "../fetch";
import { clearAccessToken, getAccessToken, isTokenExpired } from "../token";

const mockGetAccessToken = vi.mocked(getAccessToken);
const mockIsTokenExpired = vi.mocked(isTokenExpired);
const mockRefreshToken = vi.mocked(refreshToken);
const mockClearAccessToken = vi.mocked(clearAccessToken);

describe("authFetch", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.resetAllMocks();
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("adds Authorization header when token exists", async () => {
    mockGetAccessToken.mockReturnValue("valid-token");
    mockIsTokenExpired.mockReturnValue(false);
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("ok", { status: 200 }));

    await authFetch("/api/test");

    const call = vi.mocked(globalThis.fetch).mock.calls[0]!;
    const headers = call[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer valid-token");
  });

  it("omits Authorization header when no token", async () => {
    mockGetAccessToken.mockReturnValue(null);
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("ok", { status: 200 }));

    await authFetch("/api/test");

    const call = vi.mocked(globalThis.fetch).mock.calls[0]!;
    const headers = call[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBeNull();
  });

  it("proactively refreshes if token is expired within margin", async () => {
    mockGetAccessToken.mockReturnValue("old-token");
    mockIsTokenExpired.mockReturnValue(true);
    mockRefreshToken.mockResolvedValue("new-token");
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("ok", { status: 200 }));

    await authFetch("/api/test");

    expect(mockRefreshToken).toHaveBeenCalled();
    const call = vi.mocked(globalThis.fetch).mock.calls[0]!;
    const headers = call[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer new-token");
  });

  it("retries on 401 with refreshed token", async () => {
    mockGetAccessToken.mockReturnValue("expired-token");
    mockIsTokenExpired.mockReturnValue(false);
    mockRefreshToken.mockResolvedValue("refreshed-token");

    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(new Response("Unauthorized", { status: 401 }))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));

    const response = await authFetch("/api/test");

    expect(mockRefreshToken).toHaveBeenCalled();
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(2);
    expect(response.status).toBe(200);
  });

  it("clears token and redirects when refresh fails on 401", async () => {
    mockGetAccessToken.mockReturnValue("expired-token");
    mockIsTokenExpired.mockReturnValue(false);
    mockRefreshToken.mockResolvedValue(null);

    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response("Unauthorized", { status: 401 }),
    );

    await authFetch("/api/test");

    expect(mockClearAccessToken).toHaveBeenCalled();
  });

  it("passes through successful responses", async () => {
    mockGetAccessToken.mockReturnValue("token");
    mockIsTokenExpired.mockReturnValue(false);
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("data", { status: 200 }));

    const response = await authFetch("/api/test");

    expect(response.status).toBe(200);
    expect(mockRefreshToken).not.toHaveBeenCalled();
  });

  it("passes through non-401 error responses without retry", async () => {
    mockGetAccessToken.mockReturnValue("token");
    mockIsTokenExpired.mockReturnValue(false);
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("Error", { status: 500 }));

    const response = await authFetch("/api/test");

    expect(response.status).toBe(500);
    expect(mockRefreshToken).not.toHaveBeenCalled();
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
  });

  it("preserves existing request headers", async () => {
    mockGetAccessToken.mockReturnValue("token");
    mockIsTokenExpired.mockReturnValue(false);
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("ok", { status: 200 }));

    await authFetch("/api/test", {
      headers: { "Content-Type": "application/json" },
    });

    const call = vi.mocked(globalThis.fetch).mock.calls[0]!;
    const headers = call[1]?.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer token");
  });

  it("preserves request body and method", async () => {
    mockGetAccessToken.mockReturnValue("token");
    mockIsTokenExpired.mockReturnValue(false);
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("ok", { status: 200 }));

    await authFetch("/api/test", {
      method: "POST",
      body: JSON.stringify({ key: "value" }),
    });

    const call = vi.mocked(globalThis.fetch).mock.calls[0]!;
    expect(call[1]?.method).toBe("POST");
    expect(call[1]?.body).toBe('{"key":"value"}');
  });

  it("does not retry when no token present on 401", async () => {
    mockGetAccessToken.mockReturnValue(null);
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("Unauthorized", { status: 401 }));

    const response = await authFetch("/api/test");

    expect(response.status).toBe(401);
    expect(mockRefreshToken).not.toHaveBeenCalled();
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
  });
});
