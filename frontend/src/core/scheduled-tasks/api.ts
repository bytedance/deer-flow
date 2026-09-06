import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ScheduledTask, ScheduledTaskRun } from "./types";

function scheduledTasksUrl(path: string): string {
  return `${getBackendBaseURL()}/api/scheduled-tasks${path}`;
}

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

export async function fetchThreadScheduledTasks(
  threadId: string,
): Promise<ScheduledTask[]> {
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
): Promise<ScheduledTaskRun[]> {
  const response = await fetch(
    scheduledTasksUrl(`/${encodeURIComponent(taskId)}/runs`),
  );
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
  title: string;
  prompt: string;
  schedule_type: "once" | "cron";
  schedule_spec: Record<string, unknown>;
  timezone: string;
};

export async function createScheduledTask(
  payload: ScheduledTaskPayload,
): Promise<ScheduledTask> {
  const response = await fetch(scheduledTasksUrl(""), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
  payload: Partial<Omit<ScheduledTaskPayload, "thread_id" | "schedule_type">>,
): Promise<ScheduledTask> {
  const response = await fetch(
    scheduledTasksUrl(`/${encodeURIComponent(taskId)}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
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
  const response = await fetch(
    scheduledTasksUrl(`/${encodeURIComponent(taskId)}/pause`),
    { method: "POST" },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to pause scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function resumeScheduledTask(
  taskId: string,
): Promise<ScheduledTask> {
  const response = await fetch(
    scheduledTasksUrl(`/${encodeURIComponent(taskId)}/resume`),
    { method: "POST" },
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
): Promise<{ id: string; triggered: boolean }> {
  const response = await fetch(
    scheduledTasksUrl(`/${encodeURIComponent(taskId)}/trigger`),
    { method: "POST" },
  );
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
  const response = await fetch(
    scheduledTasksUrl(`/${encodeURIComponent(taskId)}`),
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to delete scheduled task: ${response.statusText}`,
    );
  }
  return response.json();
}
