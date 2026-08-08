import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch } from "@/core/api/fetcher";
import {
  cancelBackgroundTask,
  fetchBackgroundTasks,
} from "@/core/background-tasks/api";

const mockedFetch = rs.mocked(fetch);

const TASK = {
  task_id: "task-1",
  task_name: "Generate report",
  status: "working" as const,
  created_at: "2026-08-08T00:00:00+00:00",
  updated_at: "2026-08-08T00:00:01+00:00",
  error: null,
  tracking_degraded: false,
  cancel_requested: false,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("background task API", () => {
  it("loads the current thread's bounded task list", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse([TASK]));

    await expect(fetchBackgroundTasks("thread / 1")).resolves.toEqual([TASK]);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/threads/thread%20%2F%201/mcp-tasks?limit=20",
    );
  });

  it("posts cancellation through the local task id route", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({ ...TASK, status: "cancelled" }),
    );

    await expect(
      cancelBackgroundTask("thread / 1", "task / 1"),
    ).resolves.toMatchObject({ status: "cancelled" });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/threads/thread%20%2F%201/mcp-tasks/task%20%2F%201/cancel",
      { method: "POST" },
    );
  });

  it("surfaces the gateway detail on failure", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "MCP task not found" }, 404),
    );

    await expect(fetchBackgroundTasks("thread-1")).rejects.toThrow(
      "MCP task not found",
    );
  });
});
