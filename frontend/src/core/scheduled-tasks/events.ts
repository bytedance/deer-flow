import type { Message } from "@langchain/langgraph-sdk";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { useScheduledTasksFeature } from "@/core/features/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { getMessageRunId } from "@/core/messages/run-duration";
import { pathOfThread } from "@/core/threads/utils";

import { useThreadScheduledTasks } from "./hooks";
import type {
  ScheduledTask,
  ScheduledTaskRun,
  ThreadScheduledTask,
} from "./types";

/**
 * Lifecycle events of chat-created schedules, shown as one line each in the
 * chat that created the task ("Paused by agent", "Auto-paused", "Finished").
 * The backend writes them in the transaction that changes the task's state
 * (`GET /api/threads/{thread_id}/scheduled-task-events`); the names are
 * pinned by `lifecycle_events`/`lifecycle_reasons` in
 * `contracts/scheduled_goal_notes_contract.json`. Rows outlive their task:
 * they are chat history and carry a title snapshot.
 */

export const SCHEDULED_TASK_LIFECYCLE_EVENTS = [
  "task_stopped",
  "task_paused",
  "task_finished",
] as const;

export type ScheduledTaskLifecycleEvent =
  (typeof SCHEDULED_TASK_LIFECYCLE_EVENTS)[number];

export const SCHEDULED_TASK_LIFECYCLE_REASONS = {
  task_stopped: ["agent_stop"],
  task_paused: ["consecutive_unmet"],
  task_finished: ["max_runs", "end_at", "once_done", "once_failed"],
} as const satisfies Record<ScheduledTaskLifecycleEvent, readonly string[]>;

export type ScheduledTaskEvent = {
  /** For `data-*` attributes only; never shown. */
  id: string;
  /** For the "Open task" link only; never shown. */
  task_id: string;
  event: string;
  reason_code: string;
  task_title: string | null;
  /** The user's own "stop when …" words (pauses by the agent only). */
  stop_condition: string | null;
  /** The run's chat; null when the occurrence never started (a skip). */
  run_thread_id: string | null;
  run_number: number | null;
  /** How the occurrence that caused the event ended. */
  run_status: ScheduledTaskRun["status"] | null;
  max_runs: number | null;
  end_at: string | null;
  schedule_type: ScheduledTask["schedule_type"] | null;
  /** The newest run of the chat when the event was recorded (placement anchor). */
  after_run_id: string | null;
  created_at: string;
};

export function scheduledTaskEventsQueryKey(
  threadId: string | null | undefined,
) {
  return ["scheduled-tasks", "thread-events", threadId] as const;
}

export async function fetchThreadScheduledTaskEvents(
  threadId: string,
): Promise<ScheduledTaskEvent[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/scheduled-task-events`,
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load scheduled task updates: ${response.statusText}`,
    );
  }
  const body = (await response.json()) as { events?: unknown };
  return Array.isArray(body.events)
    ? (body.events as ScheduledTaskEvent[])
    : [];
}

/** Changes whenever a task of the chat changes state or finishes a run. */
export function threadTasksFingerprint(
  tasks: readonly Pick<
    ThreadScheduledTask,
    "id" | "status" | "last_run_at" | "active_run_status"
  >[],
): string {
  return tasks
    .map(
      (task) =>
        `${task.id}:${task.status}:${task.last_run_at ?? ""}:${task.active_run_status ?? ""}`,
    )
    .sort()
    .join("|");
}

/**
 * The lifecycle events of a chat, oldest first. Fetched once when a saved chat
 * opens (`staleTime: Infinity`; most chats get an empty list), and again when
 * one of the chat's tasks changes status or finishes a run, or when activity
 * polling invalidates `["scheduled-tasks"]`. Deliberately **not** gated on the
 * chat's task list: a deleted task's events still render.
 *
 * Pass `isNewThread` for a chat the backend has not created yet.
 */
export function useThreadScheduledTaskEvents(
  threadId: string | null | undefined,
  {
    isNewThread = false,
    enabled = true,
  }: { isNewThread?: boolean; enabled?: boolean } = {},
) {
  const feature = useScheduledTasksFeature();
  const active =
    enabled && !isNewThread && Boolean(threadId) && feature.available;
  const query = useQuery({
    queryKey: scheduledTaskEventsQueryKey(threadId),
    queryFn: () => fetchThreadScheduledTaskEvents(threadId ?? ""),
    enabled: active,
    staleTime: Infinity,
    retry: false,
  });

  // Same key as the chat header's task list, so this adds no request.
  const tasks = useThreadScheduledTasks(threadId, { enabled: active });
  const fingerprint = tasks.data ? threadTasksFingerprint(tasks.data) : null;
  const seen = useRef<{
    threadId: typeof threadId;
    fingerprint: string | null;
  }>({ threadId, fingerprint: null });
  const { refetch } = query;
  useEffect(() => {
    if (seen.current.threadId !== threadId) {
      seen.current = { threadId, fingerprint };
      return;
    }
    const previous = seen.current.fingerprint;
    seen.current.fingerprint = fingerprint;
    // The first task list is a baseline, not a change.
    if (active && previous !== null && fingerprint !== previous) {
      void refetch();
    }
  }, [active, fingerprint, refetch, threadId]);

  return query;
}

// ---------------------------------------------------------------------------
// Copy
// ---------------------------------------------------------------------------

export type TaskEventKind =
  | "stopped"
  | "autoPaused"
  | "finished"
  | "onceDone"
  | "onceFailed";

/** A run of the line's text: plain, the task title (bold), or the stop condition (clamped). */
export type TaskEventSegment = {
  kind: "text" | "title" | "condition";
  text: string;
};

export type TaskEventAction = {
  kind: "seeThatRun" | "openTask";
  label: string;
  href: string;
};

export type TaskEventDescription = {
  kind: TaskEventKind;
  /** The main sentence, split so the view can style the title and the condition. */
  segments: TaskEventSegment[];
  /** The last run's outcome, a separate sentence; null when it adds nothing. */
  suffix: string | null;
  /** Main sentence and suffix as plain text. */
  text: string;
  /** The full stop condition (for a tooltip when the line clamps it); null otherwise. */
  condition: string | null;
  action: TaskEventAction;
};

/** Deep link to a task on the tasks page (a deleted task shows PR1's deleted state). */
export function taskPagePath(taskId: string): string {
  return `/workspace/scheduled-tasks?task_id=${encodeURIComponent(taskId)}`;
}

function segmentsOf(
  template: string,
  values: { title: string; condition?: string; max?: number },
): TaskEventSegment[] {
  const segments: TaskEventSegment[] = [];
  const pattern = /\{(title|condition|max)\}/g;
  let last = 0;
  const pushText = (text: string) => {
    if (!text) {
      return;
    }
    const previous = segments.at(-1);
    if (previous?.kind === "text") {
      previous.text += text;
    } else {
      segments.push({ kind: "text", text });
    }
  };
  for (const match of template.matchAll(pattern)) {
    pushText(template.slice(last, match.index));
    const name = match[1];
    if (name === "title") {
      segments.push({ kind: "title", text: values.title });
    } else if (name === "condition") {
      segments.push({ kind: "condition", text: values.condition ?? "" });
    } else {
      pushText(String(values.max ?? ""));
    }
    last = (match.index ?? 0) + match[0].length;
  }
  pushText(template.slice(last));
  return segments;
}

/**
 * What goes between the main sentence and the suffix sentence. The main
 * sentence can end with the user's own stop condition, which usually has no
 * final stop, so one is added in the suffix's script ("… met: report is out.
 * The last run failed." / "…已满足：清单已完成。最后一次运行出错了。").
 * Otherwise a space in English and nothing after a full-width stop.
 */
export function sentenceGap(main: string, suffix: string): string {
  const cjkSuffix = /^[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]/.test(suffix);
  const end = main.trimEnd();
  if (/[。！？][”’」』）)]*$/.test(end)) {
    return cjkSuffix ? "" : " ";
  }
  if (/[.!?…][”’"')]*$/.test(end)) {
    return " ";
  }
  return cjkSuffix ? "。" : ". ";
}

/** The suffix as a separate sentence after the main one. */
function joinSentences(main: string, suffix: string | null): string {
  if (!suffix) {
    return main;
  }
  return `${main}${sentenceGap(main, suffix)}${suffix}`;
}

function nonEmpty(value: string | null | undefined): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/**
 * Readable copy for one event line, or `null` for an event this client does
 * not know (a newer backend). The text never contains IDs, ISO times, enum
 * names or the raw reason code.
 */
export function describeTaskEvent(
  event: ScheduledTaskEvent,
  t: Pick<Translations, "scheduledTasks">,
): TaskEventDescription | null {
  const st = t.scheduledTasks;
  const copy = st.events;
  const title = nonEmpty(event.task_title) ?? copy.untitledTask;
  const runThreadId = nonEmpty(event.run_thread_id);
  const seeThatRun: TaskEventAction | null = runThreadId
    ? {
        kind: "seeThatRun",
        label: st.notice.seeThatRun,
        href: pathOfThread(runThreadId),
      }
    : null;
  const openTask: TaskEventAction = {
    kind: "openTask",
    label: st.actions.openTask,
    href: taskPagePath(event.task_id),
  };

  let kind: TaskEventKind;
  let template: string;
  let condition: string | null = null;
  let action: TaskEventAction;
  let suffix: string | null = null;

  switch (event.event) {
    case "task_stopped": {
      kind = "stopped";
      condition = nonEmpty(event.stop_condition);
      template = condition ? copy.stoppedWithCondition : copy.stopped;
      action = seeThatRun ?? openTask;
      suffix =
        event.run_status === "failed"
          ? copy.suffixLastFailed
          : event.run_status === "unmet"
            ? copy.suffixLastUnmet
            : event.run_status === "interrupted"
              ? copy.suffixLastInterrupted
              : null;
      break;
    }
    case "task_paused": {
      kind = "autoPaused";
      template = copy.autoPaused;
      action = openTask;
      break;
    }
    case "task_finished": {
      if (event.reason_code === "once_done") {
        kind = "onceDone";
        template = copy.onceDone;
        action = seeThatRun ?? openTask;
        break;
      }
      if (event.reason_code === "once_failed") {
        kind = "onceFailed";
        template = copy.onceFailed;
        action = seeThatRun ?? openTask;
        break;
      }
      kind = "finished";
      const max = event.max_runs;
      template =
        event.reason_code === "max_runs" && typeof max === "number" && max > 0
          ? copy.finishedRuns
          : event.reason_code === "end_at"
            ? copy.finishedEnd
            : copy.finished;
      action = openTask;
      suffix =
        event.run_status === "failed"
          ? copy.suffixLastFailed
          : event.run_status === "unmet"
            ? copy.suffixLastUnmet
            : null;
      break;
    }
    default:
      return null;
  }

  const segments = segmentsOf(template, {
    title,
    condition: condition ?? undefined,
    max: event.max_runs ?? undefined,
  });
  const main = segments.map((segment) => segment.text).join("");
  return {
    kind,
    segments,
    suffix,
    text: joinSentences(main, suffix),
    condition,
    action,
  };
}

// ---------------------------------------------------------------------------
// Placement
// ---------------------------------------------------------------------------

type PlaceableGroup = { type: string; messages: Message[] };

export type PlacedTaskEvents = {
  /** Events to render right after the group at that index, oldest first. */
  afterGroup: Map<number, ScheduledTaskEvent[]>;
  /** Events with nowhere to go because there are no groups at all. */
  tail: ScheduledTaskEvent[];
};

function compareEvents(a: ScheduledTaskEvent, b: ScheduledTaskEvent): number {
  const byTime = Date.parse(a.created_at) - Date.parse(b.created_at);
  if (Number.isFinite(byTime) && byTime !== 0) {
    return byTime;
  }
  return a.created_at < b.created_at
    ? -1
    : a.created_at > b.created_at
      ? 1
      : a.id.localeCompare(b.id);
}

/**
 * Where each event line goes in the conversation. An event sits at the end of
 * the turn of its `after_run_id` (the chat's newest run when it was recorded):
 * after the last group of that turn, before the next `human` group. When no
 * message carries that run (branched or pruned history, or no anchor) it goes
 * after the last group. Lines at one position are ordered by `created_at`.
 */
export function placeTaskEvents(
  groups: readonly PlaceableGroup[],
  events: readonly ScheduledTaskEvent[],
): PlacedTaskEvents {
  const afterGroup = new Map<number, ScheduledTaskEvent[]>();
  if (groups.length === 0) {
    return { afterGroup, tail: [...events].sort(compareEvents) };
  }

  // Last group index containing each run id.
  const lastGroupOfRun = new Map<string, number>();
  groups.forEach((group, index) => {
    for (const message of group.messages) {
      const runId = getMessageRunId(message);
      if (runId) {
        lastGroupOfRun.set(runId, index);
      }
    }
  });
  const endOfTurn = (index: number) => {
    let end = index;
    while (end + 1 < groups.length && groups[end + 1]!.type !== "human") {
      end += 1;
    }
    return end;
  };

  const lastIndex = groups.length - 1;
  for (const event of events) {
    const anchor = event.after_run_id
      ? lastGroupOfRun.get(event.after_run_id)
      : undefined;
    const index = anchor === undefined ? lastIndex : endOfTurn(anchor);
    const bucket = afterGroup.get(index);
    if (bucket) {
      bucket.push(event);
    } else {
      afterGroup.set(index, [event]);
    }
  }
  for (const bucket of afterGroup.values()) {
    bucket.sort(compareEvents);
  }
  return { afterGroup, tail: [] };
}
