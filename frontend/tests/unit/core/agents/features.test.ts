import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetchAgentsApiEnabled } from "@/core/agents/api";
import { fetch as fetcher } from "@/core/api/fetcher";
import { fetchBrowserControlEnabled } from "@/core/features/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("fetchAgentsApiEnabled", () => {
  test("returns true when backend reports agents_api enabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: true } }),
    );
    await expect(fetchAgentsApiEnabled()).resolves.toBe(true);
    expect(mockedFetch).toHaveBeenCalledWith("/api/features");
  });

  test("returns false when backend reports agents_api disabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: false } }),
    );
    await expect(fetchAgentsApiEnabled()).resolves.toBe(false);
  });

  test("throws when the features request fails", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, {}));
    await expect(fetchAgentsApiEnabled()).rejects.toThrow();
  });
});

describe("fetchBrowserControlEnabled", () => {
  test("returns true when backend reports browser_control enabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        agents_api: { enabled: true },
        browser_control: { enabled: true },
      }),
    );
    await expect(fetchBrowserControlEnabled()).resolves.toBe(true);
    expect(mockedFetch).toHaveBeenCalledWith("/api/features");
  });

  test("returns false when browser_control is disabled or omitted", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        agents_api: { enabled: true },
        browser_control: { enabled: false },
      }),
    );
    await expect(fetchBrowserControlEnabled()).resolves.toBe(false);

    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: true } }),
    );
    await expect(fetchBrowserControlEnabled()).resolves.toBe(false);
  });

  test("throws when the features request fails", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, {}));
    await expect(fetchBrowserControlEnabled()).rejects.toThrow();
  });
});
