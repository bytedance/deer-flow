import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch } from "@/core/api/fetcher";
import {
  controlSubagentBatch,
  fetchSubagentBatchItems,
  fetchSubagentBatches,
  retrySubagentBatchItem,
  subagentBatchResultsUrl,
} from "@/core/subagent-batches/api";

const mockedFetch = rs.mocked(fetch);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("subagent batch API", () => {
  it("loads thread batches and items through encoded local ids", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse([]));
    await fetchSubagentBatches("thread / 1");
    expect(mockedFetch).toHaveBeenLastCalledWith(
      "/api/threads/thread%20%2F%201/subagent-batches?limit=20",
    );

    mockedFetch.mockResolvedValueOnce(jsonResponse([]));
    await fetchSubagentBatchItems("thread / 1", "batch / 1", {
      offset: 100,
      limit: 50,
      status: "failed",
    });
    expect(mockedFetch).toHaveBeenLastCalledWith(
      "/api/threads/thread%20%2F%201/subagent-batches/batch%20%2F%201/items?offset=100&limit=50&status=failed",
    );
  });

  it("posts control and failed-item retry actions", async () => {
    mockedFetch
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}));

    await controlSubagentBatch("thread-1", "batch-1", "pause");
    expect(mockedFetch).toHaveBeenLastCalledWith(
      "/api/threads/thread-1/subagent-batches/batch-1/pause",
      { method: "POST" },
    );

    await retrySubagentBatchItem("thread-1", "batch-1", "item / 1");
    expect(mockedFetch).toHaveBeenLastCalledWith(
      "/api/threads/thread-1/subagent-batches/batch-1/items/item%20%2F%201/retry",
      { method: "POST" },
    );
  });

  it("builds a JSONL export URL without putting results in chat context", () => {
    expect(subagentBatchResultsUrl("thread-1", "batch-1")).toBe(
      "/api/threads/thread-1/subagent-batches/batch-1/results.jsonl",
    );
  });
});
