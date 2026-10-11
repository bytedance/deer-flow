import { isTaskBusy, type ScheduledTask } from "./types";

export type TaskAction =
  | "pause"
  | "resume"
  | "runNow"
  | "edit"
  | "duplicate"
  | "delete";

/**
 * Why an action is disabled. UI copy: running → `actions.busyRunning`,
 * queued → `actions.busyQueued` (says Pause cancels it), queuedNoPause →
 * `actions.busyQueuedPaused` (a paused or finished task offers no Pause),
 * alreadyQueued → `actions.alreadyQueued`, createBlocked → `page.createBlocked`.
 */
export type TaskActionBlockReason =
  | "running"
  | "queued"
  | "queuedNoPause"
  | "alreadyQueued"
  | "createBlocked";

export type TaskActionState = {
  visible: boolean;
  disabled: boolean;
  reason?: TaskActionBlockReason;
};

const TERMINAL: ReadonlySet<ScheduledTask["status"]> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

function state(
  visible: boolean,
  reason?: TaskActionBlockReason,
): TaskActionState {
  return reason
    ? { visible, disabled: true, reason }
    : { visible, disabled: false };
}

/**
 * Which actions a task offers and whether they can be used now. Reads only
 * `status`, `schedule_type` and `active_run_status`, so the list, the detail
 * and the chat card agree without loading runs.
 *
 * - Pause is offered while the task can still run on its own (active or a
 *   one-time task mid-run), Resume while it is paused, or finished for a
 *   recurring task (a finished one-time task is edited instead).
 * - A starting/running run blocks every change (`running`). A queued run
 *   blocks edit, delete and resume (`queued`) but not Pause, which cancels it;
 *   Run once now would only return the waiting run (`alreadyQueued`).
 * - Duplicate is a create, so it is blocked like New task when the scheduler
 *   is off (`createBlocked`).
 */
export function availableActions(
  task: Pick<ScheduledTask, "status" | "schedule_type" | "active_run_status">,
  { createBlocked }: { createBlocked: boolean },
): Record<TaskAction, TaskActionState> {
  const busy = isTaskBusy(task);
  const queued = !busy && task.active_run_status === "queued";
  const terminal = TERMINAL.has(task.status);
  const pauseVisible = task.status === "enabled" || task.status === "running";
  // Only point at Pause when Pause is offered (a trial queued on a paused
  // task waits its turn instead).
  const blocked: TaskActionBlockReason | undefined = busy
    ? "running"
    : queued
      ? pauseVisible
        ? "queued"
        : "queuedNoPause"
      : undefined;

  const resumeVisible =
    task.status === "paused" || (terminal && task.schedule_type !== "once");

  return {
    pause: state(pauseVisible, busy ? "running" : undefined),
    resume: state(resumeVisible, blocked),
    runNow: state(
      true,
      busy ? "running" : queued ? "alreadyQueued" : undefined,
    ),
    edit: state(true, blocked),
    duplicate: state(true, createBlocked ? "createBlocked" : undefined),
    delete: state(true, blocked),
  };
}
