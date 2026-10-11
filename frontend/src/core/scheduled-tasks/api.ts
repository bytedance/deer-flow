import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  ScheduledTask,
  ScheduledTaskRenewal,
  ScheduledTaskRun,
  ScheduledTaskTriggerResult,
  ThreadScheduledTask,
} from "./types";

function scheduledTasksUrl(path: string): string {
  return `${getBackendBaseURL()}/api/scheduled-tasks${path}`;
}

function taskUrl(taskId: string, suffix = ""): string {
  return scheduledTasksUrl(`/${encodeURIComponent(taskId)}${suffix}`);
}

const JSON_HEADERS = { "Content-Type": "application/json" };

// Every failure goes through `throwGatewayApiError`, which throws a
// `GatewayApiError` carrying the coded `detail` (see core/api/errors.ts and
// core/scheduled-tasks/errors.ts for the localized copy).

export async function fetchScheduledTasks(): Promise<ScheduledTask[]> {
  const response = await fetch(scheduledTasksUrl(""));
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load scheduled tasks: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchScheduledTask(
  taskId: string,
): Promise<ScheduledTask> {
  const response = await fetch(taskUrl(taskId));
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchThreadScheduledTasks(
  threadId: string,
): Promise<ThreadScheduledTask[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/scheduled-tasks`,
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load thread scheduled tasks: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchScheduledTaskRuns(
  taskId: string,
  page?: { limit: number; offset: number; signal?: AbortSignal },
): Promise<ScheduledTaskRun[]> {
  const url = taskUrl(taskId, "/runs");
  const response = page
    ? await fetch(
        `${url}?${new URLSearchParams({ limit: String(page.limit), offset: String(page.offset) })}`,
        { signal: page.signal },
      )
    : await fetch(url);
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load scheduled task runs: ${response.statusText}`,
    );
  }
  return response.json();
}

export type ScheduledTaskPayload = {
  context_mode: "fresh_thread_per_run" | "reuse_thread";
  thread_id?: string | null;
  assistant_id?: string | null;
  title: string;
  /** Task instructions only; the stop condition is always its own field. */
  prompt: string;
  schedule_type: "once" | "cron" | "interval";
  schedule_spec: Record<string, unknown>;
  timezone: string;
  goal_objective?: string | null;
  max_runs?: number | null;
  end_at?: string | null;
  stop_condition?: string | null;
};

/**
 * PATCH body: send only changed fields. `null` clears `goal_objective`,
 * `max_runs`, `end_at` and `stop_condition`; other fields ignore `null`.
 * `schedule_type` is accepted (with `schedule_spec`), though the page keeps it
 * locked when editing.
 */
export type ScheduledTaskUpdatePayload = Partial<ScheduledTaskPayload>;

export async function createScheduledTask(
  payload: ScheduledTaskPayload,
): Promise<ScheduledTask> {
  const response = await fetch(scheduledTasksUrl(""), {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to create scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function updateScheduledTask(
  taskId: string,
  payload: ScheduledTaskUpdatePayload,
): Promise<ScheduledTask> {
  const response = await fetch(taskUrl(taskId), {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to update scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function pauseScheduledTask(
  taskId: string,
): Promise<ScheduledTask> {
  const response = await fetch(taskUrl(taskId, "/pause"), { method: "POST" });
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to pause scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}

/** Resume; `renewal` (sent as the JSON body only when given) raises or clears caps in the same request. */
export async function resumeScheduledTask(
  taskId: string,
  renewal?: ScheduledTaskRenewal,
): Promise<ScheduledTask> {
  const response = await fetch(
    taskUrl(taskId, "/resume"),
    renewal
      ? {
          method: "POST",
          headers: JSON_HEADERS,
          body: JSON.stringify(renewal),
        }
      : { method: "POST" },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to resume scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function triggerScheduledTask(
  taskId: string,
): Promise<ScheduledTaskTriggerResult> {
  const response = await fetch(taskUrl(taskId, "/trigger"), {
    method: "POST",
  });
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to trigger scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function deleteScheduledTask(
  taskId: string,
): Promise<{ id: string; deleted: boolean }> {
  const response = await fetch(taskUrl(taskId), { method: "DELETE" });
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to delete scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}
