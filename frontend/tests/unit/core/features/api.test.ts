import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch } from "@/core/api/fetcher";
import {
  fetchConversationReferencesCapability,
  fetchScheduledTasksFeature,
  fetchSubagentBatchesCapability,
} from "@/core/features/api";

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

describe("conversation references feature capability", () => {
  it("reports the flag and the per-run cap", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({
        agents_api: { enabled: true },
        conversation_references: { enabled: true, max_references: 3 },
      }),
    );

    await expect(fetchConversationReferencesCapability()).resolves.toEqual({
      enabled: true,
      maxReferences: 3,
    });
  });

  it("treats a backend without the field as disabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({ agents_api: { enabled: true } }),
    );

    await expect(fetchConversationReferencesCapability()).resolves.toEqual({
      enabled: false,
      maxReferences: 0,
    });
  });

  it("never reports a cap below zero or a non-numeric one", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({
        agents_api: { enabled: true },
        conversation_references: { enabled: true, max_references: "3" },
      }),
    );

    await expect(fetchConversationReferencesCapability()).resolves.toEqual({
      enabled: true,
      maxReferences: 0,
    });
  });
});

describe("scheduled tasks feature", () => {
  it("reads the scheduled_tasks block", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({
        agents_api: { enabled: true },
        scheduled_tasks: {
          available: true,
          running: false,
          tool_enabled: false,
          min_interval_seconds: 30,
        },
      }),
    );
    await expect(fetchScheduledTasksFeature()).resolves.toEqual({
      available: true,
      running: false,
      toolEnabled: false,
      minIntervalSeconds: 30,
    });
  });

  it("assumes a working page without the chat tool when the block is missing", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({ agents_api: { enabled: true } }),
    );
    await expect(fetchScheduledTasksFeature()).resolves.toEqual({
      available: true,
      running: true,
      toolEnabled: false,
      minIntervalSeconds: 60,
    });
  });

  it("fills missing or malformed fields with the defaults", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({
        agents_api: { enabled: true },
        scheduled_tasks: { available: false, min_interval_seconds: "10" },
      }),
    );
    await expect(fetchScheduledTasksFeature()).resolves.toEqual({
      available: false,
      running: true,
      toolEnabled: false,
      minIntervalSeconds: 60,
    });
  });
});
