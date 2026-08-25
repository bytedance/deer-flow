import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch } from "@/core/api/fetcher";
import { fetchSubagentBatchesCapability } from "@/core/features/api";

const mockedFetch = rs.mocked(fetch);

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("subagent batch feature capability", () => {
  it("keeps repository and worker availability independent", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({
        agents_api: { enabled: true },
        subagent_batches: {
          enabled: false,
          repository_available: true,
          worker_running: false,
          max_running: 3,
        },
      }),
    );

    await expect(fetchSubagentBatchesCapability()).resolves.toEqual({
      repositoryAvailable: true,
      workerRunning: false,
      maxRunning: 3,
    });
  });

  it("falls back to the legacy enabled flag during rolling upgrades", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({
        agents_api: { enabled: true },
        subagent_batches: { enabled: true, max_running: 4 },
      }),
    );

    await expect(fetchSubagentBatchesCapability()).resolves.toEqual({
      repositoryAvailable: true,
      workerRunning: true,
      maxRunning: 4,
    });
  });
});
