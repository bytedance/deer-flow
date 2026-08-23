import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetchAgentsApiEnabled } from "@/core/agents/api";
import { fetch as fetcher } from "@/core/api/fetcher";
import {
  fetchBrowserControlEnabled,
  fetchKnowledgeBaseEnabled,
  fetchKnowledgeBaseFeature,
  fetchMcpTasksEnabled,
} from "@/core/features/api";

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

describe("fetchMcpTasksEnabled", () => {
  test("returns true when backend reports mcp_tasks enabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        agents_api: { enabled: true },
        mcp_tasks: { enabled: true },
      }),
    );
    await expect(fetchMcpTasksEnabled()).resolves.toBe(true);
    expect(mockedFetch).toHaveBeenCalledWith("/api/features");
  });

  test("returns false when mcp_tasks is disabled or omitted", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        agents_api: { enabled: true },
        mcp_tasks: { enabled: false },
      }),
    );
    await expect(fetchMcpTasksEnabled()).resolves.toBe(false);

    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: true } }),
    );
    await expect(fetchMcpTasksEnabled()).resolves.toBe(false);
  });

  test("throws when the features request fails", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, {}));
    await expect(fetchMcpTasksEnabled()).rejects.toThrow();
  });
});

describe("fetchKnowledgeBaseFeature", () => {
  test("reads the knowledge_base feature flag and management URL", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        agents_api: { enabled: true },
        knowledge_base: {
          enabled: true,
          management_url: "http://ragflow.example",
        },
      }),
    );
    await expect(fetchKnowledgeBaseEnabled()).resolves.toBe(true);

    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        knowledge_base: { enabled: true, management_url: null },
      }),
    );
    await expect(fetchKnowledgeBaseFeature()).resolves.toEqual({
      enabled: true,
      managementUrl: null,
    });
  });

  test("defaults to disabled when omitted", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { agents_api: { enabled: true } }));
    await expect(fetchKnowledgeBaseEnabled()).resolves.toBe(false);
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, {}));
    await expect(fetchKnowledgeBaseFeature()).resolves.toEqual({
      enabled: false,
      managementUrl: null,
    });
  });
});
