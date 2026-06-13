import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/core/api/fetcher", () => ({
  fetch: vi.fn(),
}));

import { fetch } from "@/core/api/fetcher";
import { MCPConfigRequestError, loadMCPConfig } from "@/core/mcp/api";

const mockedFetch = vi.mocked(fetch);

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retryDelay: 0,
      },
    },
  });
}

describe("useMCPConfig retry policy", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("does not retry when loadMCPConfig throws MCPConfigRequestError (403)", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Forbidden" }),
    } as Response);

    const client = makeClient();
    await expect(
      client.fetchQuery({
        queryKey: ["mcpConfig"],
        queryFn: () => loadMCPConfig(),
        retry: (count, error) =>
          !(error instanceof MCPConfigRequestError) && count < 3,
      }),
    ).rejects.toBeInstanceOf(MCPConfigRequestError);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it("retries up to 3 times on generic errors", async () => {
    mockedFetch.mockRejectedValue(new Error("network down"));

    const client = makeClient();
    await expect(
      client.fetchQuery({
        queryKey: ["mcpConfig"],
        queryFn: () => loadMCPConfig(),
        retry: (count, error) =>
          !(error instanceof MCPConfigRequestError) && count < 3,
      }),
    ).rejects.toThrow("network down");

    // initial + 3 retries = 4 calls
    expect(mockedFetch).toHaveBeenCalledTimes(4);
  });

  it("does not retry on MCPConfigRequestError 5xx either (deterministic typed error)", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Boom" }),
    } as Response);

    const client = makeClient();
    await expect(
      client.fetchQuery({
        queryKey: ["mcpConfig"],
        queryFn: () => loadMCPConfig(),
        retry: (count, error) =>
          !(error instanceof MCPConfigRequestError) && count < 3,
      }),
    ).rejects.toBeInstanceOf(MCPConfigRequestError);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });
});
