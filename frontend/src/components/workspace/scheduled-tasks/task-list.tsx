"use client";

import {
  Ban,
  Bot,
  CalendarClock,
  CircleCheck,
  CirclePause,
  CircleX,
  Clock,
  LoaderCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { describeTaskSchedule } from "@/core/scheduled-tasks/cron";
import { displayTimeZone, formatTaskTime } from "@/core/scheduled-tasks/format";
import { describeTaskOutcome } from "@/core/scheduled-tasks/goal-outcome";
import { presentTaskStatus } from "@/core/scheduled-tasks/status";
import { isTaskBusy, type ScheduledTask } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

import { fill } from "./shared";

export type TaskLineTone = "neutral" | "ok" | "info" | "warn" | "danger";

export type TaskStatusLine = {
  text: string;
  tone: TaskLineTone;
  icon: LucideIcon;
};

/**
 * The one status line under a task in the list: when it runs next, that it is
 * running now, or who stopped it and why. Never an ISO time or enum name.
 */
export function taskListStatusLine(
  task: ScheduledTask,
  t: Translations,
  locale: string,
  now: Date = new Date(),
): TaskStatusLine {
  const st = t.scheduledTasks;
  const time = (iso: string | null | undefined) =>
    iso
      ? formatTaskTime(iso, {
          timeZone: displayTimeZone(task),
          locale,
          labels: st.time,
          now,
        })
      : "";
  if (isTaskBusy(task)) {
    return { text: st.list.runningNow, tone: "info", icon: LoaderCircle };
  }
  if (task.active_run_status === "queued") {
    return { text: st.actions.alreadyQueued, tone: "info", icon: Clock };
  }
  const status = presentTaskStatus(task);
  switch (status.key) {
    case "active": {
      const next = time(task.next_run_at);
      return next
        ? { text: fill(st.list.next, { time: next }), tone: "ok", icon: Clock }
        : { text: st.status.enabled, tone: "ok", icon: CalendarClock };
    }
    case "pausedByAgent": {
      const at = time(task.last_run_at);
      return {
        text: at
          ? fill(st.list.pausedByAgentOn, { time: at })
          : st.status.pausedByAgent,
        tone: "info",
        icon: Bot,
      };
    }
    case "autoPaused":
      return {
        text: st.list.autoPausedLine,
        tone: "warn",
        icon: TriangleAlert,
      };
    case "paused":
      return { text: st.status.paused, tone: "neutral", icon: CirclePause };
    case "finished": {
      const outcome = describeTaskOutcome(task, [], now);
      if (outcome?.kind === "limitReached") {
        return {
          text: fill(st.list.finishedLimit, { max: outcome.max }),
          tone: "neutral",
          icon: CircleCheck,
        };
      }
      if (outcome?.kind === "endReached") {
        return {
          text: st.list.finishedEnd,
          tone: "neutral",
          icon: CircleCheck,
        };
      }
      return { text: st.status.completed, tone: "neutral", icon: CircleCheck };
    }
    case "failed":
      return { text: st.status.failed, tone: "danger", icon: CircleX };
    case "cancelled":
      return { text: st.status.cancelled, tone: "neutral", icon: Ban };
    case "running":
      return { text: st.list.runningNow, tone: "info", icon: LoaderCircle };
  }
}

export const TONE_CLASS: Record<TaskLineTone, string> = {
  neutral: "text-muted-foreground",
  ok: "text-emerald-700 dark:text-emerald-400",
  info: "text-sky-700 dark:text-sky-400",
  warn: "text-amber-700 dark:text-amber-400",
  danger: "text-destructive",
};

export function TaskList({
  tasks,
  selectedId,
  onSelect,
}: {
  tasks: ScheduledTask[];
  selectedId: string | null;
  onSelect: (taskId: string) => void;
}) {
  const { t, locale } = useI18n();
  return (
    <ul
      className="flex flex-col gap-2"
      data-testid="scheduled-task-list"
      aria-label={t.sidebar.scheduledTasks}
    >
      {tasks.map((task) => {
        const selected = task.id === selectedId;
        const line = taskListStatusLine(task, t, locale);
        const LineIcon = line.icon;
        return (
          <li key={task.id}>
            <button
              type="button"
              aria-current={selected ? "true" : undefined}
              onClick={() => onSelect(task.id)}
              data-testid={`scheduled-task-item-${task.id}`}
              data-task-id={task.id}
              className={cn(
                "bg-card hover:bg-accent/40 flex w-full gap-3 rounded-lg border p-3 text-left transition-colors",
                selected
                  ? "border-foreground ring-foreground ring-1"
                  : "border-border",
              )}
            >
              <span className="bg-muted text-muted-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md">
                <CalendarClock className="size-4" aria-hidden />
              </span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-sm font-semibold">
                  {task.title}
                </span>
                <span className="text-muted-foreground truncate text-xs">
                  {
                    describeTaskSchedule(task, locale, {
                      time: t.scheduledTasks.time,
                    }).text
                  }
                </span>
                <span
                  className={cn(
                    "flex items-center gap-1 text-xs",
                    TONE_CLASS[line.tone],
                  )}
                >
                  <LineIcon
                    className={cn(
                      "size-3.5 shrink-0",
                      line.icon === LoaderCircle && "animate-spin",
                    )}
                    aria-hidden
                  />
                  <span className="truncate">{line.text}</span>
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
