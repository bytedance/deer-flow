import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { fetchGateway } from "@/core/api/fetch-gateway";
import { DEFAULT_TENANT_ID, setCurrentTenantId } from "@/core/tenant";

function mockResponse(status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve({}),
  };
}

describe("fetchGateway", () => {
  beforeEach(() => {
    vi.stubGlobal("document", {
      cookie: "csrf_token=test-csrf-token",
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse()));
  });

  afterEach(() => {
    setCurrentTenantId(DEFAULT_TENANT_ID);
    vi.unstubAllGlobals();
  });

  test("adds credentials and CSRF header for POST requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse());
    vi.stubGlobal("fetch", fetchMock);

    await fetchGateway("http://localhost:8001/api/threads/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 10 }),
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://localhost:8001/api/threads/search");
    expect(init?.credentials).toBe("include");

    const headers = new Headers(init?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-CSRF-Token")).toBe("test-csrf-token");
  });

  test("preserves tenant header injection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse());
    vi.stubGlobal("fetch", fetchMock);
    setCurrentTenantId("tenant-a");

    await fetchGateway("http://localhost:8001/api/models");

    const [, init] = fetchMock.mock.calls[0]!;
    const headers = new Headers(init?.headers);
    expect(headers.get("X-DeerFlow-Tenant")).toBe("tenant-a");
  });
});
