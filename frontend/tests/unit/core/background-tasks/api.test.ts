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
  fetchBackgroundTask,
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

  it("loads one task's bounded detail through local ids", async () => {
    const detail = {
      ...TASK,
      status: "completed" as const,
      result: { summary: "Quarterly report ready" },
      result_preview: null,
      result_truncated: false,
      result_artifact: null,
      input_required: null,
      last_poll_error: null,
      last_polled_at: "2026-08-08T00:02:00+00:00",
      notification_status: "delivered" as const,
      notification_error: null,
      notification_attempt_count: 0,
    };
    mockedFetch.mockResolvedValueOnce(jsonResponse(detail));

    await expect(
      fetchBackgroundTask("thread / 1", "task / 1"),
    ).resolves.toEqual(detail);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/threads/thread%20%2F%201/mcp-tasks/task%20%2F%201",
    );
  });

  it("posts cancellation through the local task id route", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({ ...TASK, cancel_requested: true }),
    );

    await expect(
      cancelBackgroundTask("thread / 1", "task / 1"),
    ).resolves.toMatchObject({
      status: "working",
      cancel_requested: true,
    });
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
