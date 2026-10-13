/**
 * The `schedule_task` tool result as the chat card reads it. The backend
 * capability returns `{action, display, task, ...}` (see
 * `backend/app/gateway/scheduled_task_access.py` `_task_view`); LangChain
 * serializes that dict to JSON in the tool message. Only results that change
 * or show one task become a card; `list`, `note` and errors do not.
 */

import { zonedLocalToUtcIso } from "./cron";
import type {
  ScheduledTask,
  ScheduledTaskActiveRunStatus,
  ScheduledTaskStatus,
} from "./types";

export const SCHEDULE_TASK_TOOL_NAME = "schedule_task";

export type ScheduleCardAction =
  | "create"
  | "update"
  | "pause"
  | "resume"
  | "trial"
  | "delete";

const CARD_ACTIONS: ReadonlySet<string> = new Set<ScheduleCardAction>([
  "create",
  "update",
  "pause",
  "resume",
  "trial",
  "delete",
]);

/** The task projection the tool returns (`_task_view`); `delete` returns only id and title. */
export type ScheduleToolTask = {
  id: string;
  title?: string | null;
  status?: ScheduledTaskStatus;
  schedule_type?: ScheduledTask["schedule_type"];
  schedule_spec?: Record<string, unknown>;
  timezone?: string;
  /** "2026-10-07 09:00 (Asia/Shanghai)"; model-facing, never rendered as is. */
  next_run_local?: string | null;
  active_run_status?: ScheduledTaskActiveRunStatus | null;
  prompt?: string | null;
  stop_condition?: string | null;
  goal_objective?: string | null;
  max_runs?: number | null;
  /** Same format as `next_run_local`. */
  end_at_local?: string | null;
  automatic_runs_used?: number;
  context_mode?: ScheduledTask["context_mode"];
  standing_notes?: string[];
};

export type ScheduleToolResult = {
  action: ScheduleCardAction;
  display: "card" | "text";
  task: ScheduleToolTask;
  trial?: {
    outcome?: "launched" | "queued";
    existing?: boolean;
    thread_id?: string | null;
  };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function contentText(content: unknown): string | null {
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((part) =>
        typeof part === "string"
          ? part
          : isRecord(part) &&
              part.type === "text" &&
              typeof part.text === "string"
            ? part.text
            : "",
      )
      .join("");
  }
  return null;
}

/**
 * Parse a `schedule_task` tool message's content into a card result, or null
 * for anything that is not a successful create/update/pause/resume/trial/delete
 * of one task (lists, notes, coded errors, legacy or unparsable text).
 */
export function parseScheduleToolResult(
  content: unknown,
): ScheduleToolResult | null {
  const text = contentText(content);
  let value: unknown = isRecord(content) ? content : null;
  if (text !== null) {
    try {
      value = JSON.parse(text);
    } catch {
      return null;
    }
  }
  if (!isRecord(value) || "error" in value) {
    return null;
  }
  const { action, display, task, trial } = value;
  if (typeof action !== "string" || !CARD_ACTIONS.has(action)) {
    return null;
  }
  if (!isRecord(task) || typeof task.id !== "string" || !task.id) {
    return null;
  }
  return {
    action: action as ScheduleCardAction,
    display: display === "text" ? "text" : "card",
    task: task as ScheduleToolTask,
    ...(isRecord(trial) ? { trial: trial as ScheduleToolResult["trial"] } : {}),
  };
}

const LOCAL_TIME = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) \(([^)]+)\)$/;

/** "2026-10-07 09:00 (Asia/Shanghai)" → UTC ISO, or null. */
export function localTimeToIso(
  value: string | null | undefined,
): string | null {
  const match = typeof value === "string" ? LOCAL_TIME.exec(value) : null;
  if (!match) {
    return null;
  }
  try {
    return zonedLocalToUtcIso(`${match[1]}T${match[2]}`, match[3]!);
  } catch {
    return null;
  }
}

/**
 * The tool's task snapshot shaped as a `ScheduledTask`, used as the card's
 * first paint until the live task loads. Fields the snapshot does not carry
 * (last run, last error, agent) are empty; the live fetch fills them.
 */
export function snapshotToTask(snapshot: ScheduleToolTask): ScheduledTask {
  return {
    id: snapshot.id,
    thread_id: null,
    context_mode: snapshot.context_mode ?? "fresh_thread_per_run",
    assistant_id: null,
    title: snapshot.title ?? "",
    prompt: snapshot.prompt ?? "",
    schedule_type: snapshot.schedule_type ?? "once",
    schedule_spec: snapshot.schedule_spec ?? {},
    timezone: snapshot.timezone ?? "UTC",
    status: snapshot.status ?? "enabled",
    next_run_at: localTimeToIso(snapshot.next_run_local),
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    // Not in the snapshot; launched scheduled runs are the closest count.
    run_count: snapshot.automatic_runs_used ?? 0,
    goal_objective: snapshot.goal_objective ?? null,
    max_runs: snapshot.max_runs ?? null,
    end_at: localTimeToIso(snapshot.end_at_local),
    standing_notes: snapshot.standing_notes ?? [],
    stop_condition: snapshot.stop_condition ?? null,
    automatic_runs_used: snapshot.automatic_runs_used ?? 0,
    active_run_status: snapshot.active_run_status ?? null,
    created_at: "",
    updated_at: "",
  };
}
