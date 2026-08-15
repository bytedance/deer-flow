export type BackgroundTaskStatus =
  | "submitted"
  | "working"
  | "input_required"
  | "completed"
  | "failed"
  | "cancelled";

export type BackgroundTask = {
  task_id: string;
  task_name: string;
  status: BackgroundTaskStatus;
  created_at: string;
  updated_at: string;
  error: string | null;
  tracking_degraded: boolean;
  cancel_requested: boolean;
};

export type BackgroundTaskDetail = BackgroundTask & {
  last_polled_at: string | null;
  last_poll_error: string | null;
  last_cancel_error: string | null;
  cancel_attempt_count: number;
  result: unknown | null;
  result_preview: string | null;
  result_truncated: boolean;
  result_artifact: unknown | null;
  input_required: unknown | null;
};

export const ACTIVE_BACKGROUND_TASK_STATUSES: ReadonlySet<BackgroundTaskStatus> =
  new Set(["submitted", "working", "input_required"]);

export function isActiveBackgroundTask(task: BackgroundTask): boolean {
  return ACTIVE_BACKGROUND_TASK_STATUSES.has(task.status);
}
