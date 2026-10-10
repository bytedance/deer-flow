import type { ScheduledTaskRun } from "./types";

/** Keys of `t.scheduledTasks.runErrors`. */
export type RunErrorKey =
  | "restarted"
  | "leaseLost"
  | "queueTimeout"
  | "pausedWhileQueued"
  | "deletedWhileQueued"
  | "endReached"
  | "interrupted"
  | "launchFailed"
  | "failed";

/**
 * Host-written run errors (backend `deerflow/scheduler/host_notes.py`), pinned
 * by `host_run_errors` in contracts/scheduled_goal_notes_contract.json.
 */
export const HOST_RUN_ERRORS: Readonly<Record<string, RunErrorKey>> = {
  "interrupted: gateway restarted before the run reached a terminal state":
    "restarted",
  "interrupted: the owning gateway stopped renewing its run lease": "leaseLost",
  "scheduled task queue wait timeout exceeded": "queueTimeout",
  "scheduled task was paused while queued": "pausedWhileQueued",
  "scheduled task was deleted while queued": "deletedWhileQueued",
  "schedule end condition reached": "endReached",
  "run was interrupted before completion": "interrupted",
};

export type RunErrorDescription = {
  key: RunErrorKey;
  /** The stored error text, for a "Details" disclosure; null for host-written notes. */
  raw: string | null;
};

/**
 * Readable reason for a run that failed, was interrupted or was skipped. A
 * host-written note maps to its own key; a run that never got an agent run
 * (`run_id == null`) failed to start; anything else is a failure whose raw
 * text stays behind "Details". Goal outcomes (`unmet`, met) and runs still in
 * progress return null.
 */
export function describeRunError(
  run: Pick<ScheduledTaskRun, "status" | "error" | "run_id">,
): RunErrorDescription | null {
  const error = run.error?.trim() ? run.error : null;
  if (error) {
    const key = HOST_RUN_ERRORS[error];
    if (key) {
      return { key, raw: null };
    }
  }
  if (
    run.status !== "failed" &&
    run.status !== "interrupted" &&
    run.status !== "skipped"
  ) {
    return null;
  }
  if (run.status === "failed" && run.run_id == null) {
    return { key: "launchFailed", raw: error };
  }
  if (run.status === "interrupted") {
    return { key: "interrupted", raw: error };
  }
  if (run.status === "skipped" && !error) {
    return null;
  }
  return { key: "failed", raw: error };
}
