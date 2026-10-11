import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

import { GatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import {
  createScheduledTask,
  fetchScheduledTask,
  fetchScheduledTasks,
  resumeScheduledTask,
  triggerScheduledTask,
  updateScheduledTask,
  type ScheduledTaskPayload,
} from "@/core/scheduled-tasks/api";
import {
  ACTIVE_POLL_MS,
  IDLE_POLL_MS,
  scheduledTaskRefetchInterval,
  scheduledTasksRefetchInterval,
} from "@/core/scheduled-tasks/hooks";
import { runHistoryRefetchInterval } from "@/core/scheduled-tasks/run-history";
import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";

const mockedFetch = rs.mocked(fetch);

const SAMPLE_TASK = {
  id: "task-1",
  thread_id: null as string | null,
  context_mode: "fresh_thread_per_run" as const,
  last_thread_id: null as string | null,
  title: "Daily summary",
  prompt: "Summarize thread",
  schedule_type: "cron" as const,
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "UTC",
  status: "enabled" as const,
  next_run_at: "2026-07-02T01:00:00+00:00",
  last_run_at: null,
  last_run_id: null,
  last_error: null,
  run_count: 0,
  created_at: "2026-07-01T00:00:00+00:00",
  updated_at: "2026-07-01T00:00:00+00:00",
};

function jsonResponse(body: unknown, ok = true): Response {
  return {
    ok,
    status: 200,
    statusText: "OK",
    json: async () => body,
  } as Response;
}

function errorResponse(
  detail: string,
  status = 400,
  statusText = "Bad Request",
): Response {
  return {
    ok: false,
    status,
    statusText,
    json: async () => ({ detail }),
  } as Response;
}

describe("scheduled tasks api", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("fetchScheduledTasks hits GET /api/scheduled-tasks", async () => {
    mockedFetch.mockResolvedValue(jsonResponse([SAMPLE_TASK]));

    const result = await fetchScheduledTasks();

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const call = mockedFetch.mock.calls[0];
    expect(call).toBeDefined();
    const url = String(call?.[0] as string);
    expect(url).toContain("/api/scheduled-tasks");
    expect(call?.[1]?.method).toBeUndefined();
    expect(result).toEqual([SAMPLE_TASK]);
  });

  it("createScheduledTask hits POST /api/scheduled-tasks with payload", async () => {
    mockedFetch.mockResolvedValue(jsonResponse(SAMPLE_TASK));

    const payload: ScheduledTaskPayload = {
      context_mode: "fresh_thread_per_run",
      thread_id: null,
      assistant_id: "research-bot",
      title: "Daily summary",
      prompt: "Summarize thread",
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * *" },
      timezone: "UTC",
    };
    const result = await createScheduledTask(payload);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const call = mockedFetch.mock.calls[0];
    expect(call).toBeDefined();
    const url = String(call?.[0] as string);
    expect(url).toContain("/api/scheduled-tasks");
    expect(call?.[1]?.method).toBe("POST");
    const body = call?.[1]?.body as string;
    expect(JSON.parse(body)).toEqual(payload);
    expect(result).toEqual(SAMPLE_TASK);
  });

  it("throws an Error carrying backend detail on failure", async () => {
    mockedFetch.mockResolvedValue(
      errorResponse("Cron expression is invalid", 422, "Unprocessable Entity"),
    );

    await expect(fetchScheduledTasks()).rejects.toThrow(
      "Cron expression is invalid",
    );
  });

  it("falls back to a generic message when detail is missing", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      // body is not valid JSON → body.detail is undefined → fallback used
      json: async () => {
        throw new SyntaxError("Unexpected token");
      },
    } as unknown as Response);

    await expect(fetchScheduledTasks()).rejects.toThrow(/Failed to load/);
  });
});

describe("scheduled task api: single task, renewal, trigger", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("fetchScheduledTask hits GET /api/scheduled-tasks/{id}", async () => {
    mockedFetch.mockResolvedValue(jsonResponse(SAMPLE_TASK));
    await expect(fetchScheduledTask("task 1")).resolves.toEqual(SAMPLE_TASK);
    expect(String(mockedFetch.mock.calls[0]?.[0] as string)).toContain(
      "/api/scheduled-tasks/task%201",
    );
  });

  it("a coded 404 rejects with task_not_found", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({
        detail: { code: "task_not_found", message: "Scheduled task not found" },
      }),
    } as Response);
    const error = await fetchScheduledTask("gone").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(GatewayApiError);
    expect((error as GatewayApiError).code).toBe("task_not_found");
    expect((error as GatewayApiError).status).toBe(404);
  });

  it("resume sends a JSON body only when a renewal is given", async () => {
    mockedFetch.mockResolvedValue(jsonResponse(SAMPLE_TASK));
    await resumeScheduledTask("task-1");
    expect(mockedFetch.mock.calls[0]?.[1]).toEqual({ method: "POST" });

    await resumeScheduledTask("task-1", { max_runs: null });
    const init = mockedFetch.mock.calls[1]?.[1];
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ max_runs: null });
    expect(String(mockedFetch.mock.calls[1]?.[0] as string)).toContain(
      "/api/scheduled-tasks/task-1/resume",
    );
  });

  it("update sends null to clear a cap and keeps prompt and stop condition apart", async () => {
    mockedFetch.mockResolvedValue(jsonResponse(SAMPLE_TASK));
    await updateScheduledTask("task-1", {
      stop_condition: "every item is checked",
      max_runs: null,
    });
    expect(JSON.parse(mockedFetch.mock.calls[0]?.[1]?.body as string)).toEqual({
      stop_condition: "every item is checked",
      max_runs: null,
    });
  });

  it("trigger returns the outcome, the existing flag and the run's chat", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({
        id: "task-1",
        triggered: true,
        outcome: "queued",
        existing: true,
        thread_id: null,
      }),
    );
    await expect(triggerScheduledTask("task-1")).resolves.toEqual({
      id: "task-1",
      triggered: true,
      outcome: "queued",
      existing: true,
      thread_id: null,
    });
  });
});

describe("polling intervals", () => {
  const task = (overrides: Partial<ScheduledTask>) =>
    ({ ...SAMPLE_TASK, ...overrides }) as ScheduledTask;

  it("the list polls fast while any task has an active run", () => {
    expect(scheduledTasksRefetchInterval(undefined)).toBe(IDLE_POLL_MS);
    expect(scheduledTasksRefetchInterval([task({})])).toBe(IDLE_POLL_MS);
    expect(
      scheduledTasksRefetchInterval([task({}), task({ status: "running" })]),
    ).toBe(ACTIVE_POLL_MS);
    // A recurring task stays enabled while its occurrence runs.
    expect(
      scheduledTasksRefetchInterval([
        task({ status: "enabled", active_run_status: "running" }),
      ]),
    ).toBe(3000);
    expect(
      scheduledTasksRefetchInterval([task({ active_run_status: "queued" })]),
    ).toBe(3000);
    expect(IDLE_POLL_MS).toBe(15000);
  });

  it("a single task polls only while live", () => {
    expect(scheduledTaskRefetchInterval(task({}), false)).toBe(false);
    expect(
      scheduledTaskRefetchInterval(
        task({ active_run_status: "running" }),
        false,
      ),
    ).toBe(false);
    expect(scheduledTaskRefetchInterval(task({}), true)).toBe(15000);
    expect(
      scheduledTaskRefetchInterval(
        task({ active_run_status: "launching" }),
        true,
      ),
    ).toBe(3000);
    expect(scheduledTaskRefetchInterval(undefined, true)).toBe(15000);
  });

  it("run history polls the latest page fast while a loaded run is active", () => {
    const runs = (status: ScheduledTaskRun["status"]) =>
      [{ id: "r", status }] as ScheduledTaskRun[];
    expect(runHistoryRefetchInterval(runs("success"), 0)).toBe(15000);
    expect(runHistoryRefetchInterval(runs("queued"), 0)).toBe(3000);
    expect(runHistoryRefetchInterval(runs("running"), 0)).toBe(3000);
    expect(runHistoryRefetchInterval(runs("running"), 1)).toBe(false);
    expect(runHistoryRefetchInterval(undefined, 0)).toBe(15000);
  });
});
