import {
  Ban,
  Bot,
  CalendarClock,
  CircleCheck,
  CirclePause,
  CircleX,
  LoaderCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { describeTaskLastError } from "./goal-outcome";
import { isTaskBusy, type ScheduledTask } from "./types";

/** Keys of `t.scheduledTasks.status` used for a task's badge. */
export type TaskStatusKey =
  | "active"
  | "paused"
  | "pausedByAgent"
  | "autoPaused"
  | "running"
  | "finished"
  | "failed"
  | "cancelled";

export type TaskStatusTone = "neutral" | "info" | "warn" | "ok" | "danger";

export type TaskStatusPresentation = {
  key: TaskStatusKey;
  tone: TaskStatusTone;
  icon: LucideIcon;
};

/**
 * Badge for a task. "Running now" wins whenever a run is starting or running,
 * including a recurring task whose `status` stays `enabled` while its
 * occurrence runs. A pause by the agent or by three missed goals keeps
 * `status: "paused"` and is told apart by the host-written `last_error`.
 */
export function presentTaskStatus(
  task: Pick<ScheduledTask, "status" | "active_run_status" | "last_error">,
): TaskStatusPresentation {
  if (isTaskBusy(task)) {
    return { key: "running", tone: "info", icon: LoaderCircle };
  }
  switch (task.status) {
    case "enabled":
      return { key: "active", tone: "ok", icon: CalendarClock };
    case "paused": {
      const note = describeTaskLastError(task.last_error);
      if (note?.kind === "agentStop") {
        return { key: "pausedByAgent", tone: "info", icon: Bot };
      }
      if (note?.kind === "autoPause") {
        return { key: "autoPaused", tone: "warn", icon: TriangleAlert };
      }
      return { key: "paused", tone: "neutral", icon: CirclePause };
    }
    case "completed":
      return { key: "finished", tone: "neutral", icon: CircleCheck };
    case "failed":
      return { key: "failed", tone: "danger", icon: CircleX };
    case "cancelled":
      return { key: "cancelled", tone: "neutral", icon: Ban };
    case "running":
      return { key: "running", tone: "info", icon: LoaderCircle };
  }
}

/** Localized label for a badge key (`active` reads `status.enabled`, `finished` reads `status.completed`). */
export function taskStatusLabel(
  key: TaskStatusKey,
  labels: {
    enabled: string;
    paused: string;
    running: string;
    completed: string;
    failed: string;
    cancelled: string;
    pausedByAgent: string;
    autoPaused: string;
  },
): string {
  switch (key) {
    case "active":
      return labels.enabled;
    case "finished":
      return labels.completed;
    default:
      return labels[key];
  }
}
