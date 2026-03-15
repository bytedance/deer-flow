import { describe, expect, it, vi } from "vitest";

const clientCtor = vi.fn().mockImplementation(function (
  this: Record<string, unknown>,
  opts: { apiUrl: string },
) {
  this.apiUrl = opts.apiUrl;
  this.runs = {
    stream: vi.fn(),
    joinStream: vi.fn(),
  };
});

vi.mock("@langchain/langgraph-sdk/client", () => ({
  Client: clientCtor,
}));

vi.mock("../config", () => ({
  getLangGraphBaseURL: (isMock?: boolean) =>
    isMock ? "http://mock" : "http://prod",
}));

describe("getAPIClient", () => {
  it("caches clients by api url", async () => {
    const { getAPIClient } = await import("./api-client");

    const prodA = getAPIClient(false);
    const prodB = getAPIClient(false);
    const mockA = getAPIClient(true);

    expect(prodA).toBe(prodB);
    expect(mockA).not.toBe(prodA);
    expect(clientCtor).toHaveBeenCalledTimes(2);
  });
});
