"use client";

import {
  ArrowUpRight,
  CalendarClock,
  CalendarX2,
  Flag,
  MessageSquare,
  Pause,
  Play,
  Repeat,
  RotateCcw,
  Target,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  blockReasonText,
  fill,
  taskChatPath,
  WithReason,
} from "@/components/workspace/scheduled-tasks/shared";
import {
  nextRunLine,
  stopLines,
} from "@/components/workspace/scheduled-tasks/task-detail";
import { GatewayApiError } from "@/core/api/errors";
import { useScheduledTasksFeature } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { availableActions } from "@/core/scheduled-tasks/actions";
import { describeTaskSchedule } from "@/core/scheduled-tasks/cron";
import { toastScheduledTaskError } from "@/core/scheduled-tasks/error-toast";
import {
  describeScheduledTaskError,
  shouldReportScheduledTaskError,
} from "@/core/scheduled-tasks/errors";
import { displayTimeZone, formatTaskTime } from "@/core/scheduled-tasks/format";
import { describeTaskOutcome } from "@/core/scheduled-tasks/goal-outcome";
import {
  useInView,
  usePauseScheduledTask,
  useResumeScheduledTask,
  useScheduledTask,
  useTriggerScheduledTask,
} from "@/core/scheduled-tasks/hooks";
import {
  presentTaskStatus,
  taskStatusLabel,
} from "@/core/scheduled-tasks/status";
import {
  snapshotToTask,
  type ScheduleToolResult,
} from "@/core/scheduled-tasks/tool-result";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

const BADGE_TONE: Record<string, string> = {
  neutral: "bg-muted text-muted-foreground",
  ok: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  info: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  warn: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
  danger: "bg-destructive/10 text-destructive",
};

/** Deep link to the task on the tasks page. */
export function taskPagePath(taskId: string): string {
  return `/workspace/scheduled-tasks?task_id=${encodeURIComponent(taskId)}`;
}

function Row({
  icon,
  label,
  children,
}: {
  icon: ReactNode;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 gap-1 border-t px-4 py-3 text-sm sm:grid-cols-[7.5rem_minmax(0,1fr)] sm:gap-3">
      <div className="text-muted-foreground flex items-start gap-2">
        <span className="mt-0.5 shrink-0" aria-hidden>
          {icon}
        </span>
        <span>{label}</span>
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function isNotFound(error: unknown): boolean {
  return error instanceof GatewayApiError && error.status === 404;
}

/**
 * The live card a `schedule_task` result renders as in chat (mockups m1/m2).
 * The tool's snapshot paints first; the task is then read from the API and
 * polled while the card is on screen, so it follows pauses, runs and edits
 * made anywhere. Buttons call the REST API directly: a click is consent.
 */
export function ScheduledTaskCard({
  result,
  className,
}: {
  result: ScheduleToolResult;
  className?: string;
}) {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref);
  const feature = useScheduledTasksFeature();
  const deletedByResult = result.action === "delete";
  const snapshot = useMemo(() => snapshotToTask(result.task), [result.task]);
  const query = useScheduledTask(result.task.id, {
    enabled: !deletedByResult,
    initialData: deletedByResult ? undefined : snapshot,
    live: inView,
  });
  const deleted = deletedByResult || isNotFound(query.error);
  const task: ScheduledTask = query.data ?? snapshot;
  const title = task.title ? task.title : (result.task.title ?? "");

  const pause = usePauseScheduledTask();
  const resume = useResumeScheduledTask({ toastOnError: false });
  const trigger = useTriggerScheduledTask();
  const triggerGuard = useRef(false);
  const [trialThreadId, setTrialThreadId] = useState<string | null>(null);
  const [limitMessage, setLimitMessage] = useState<string | null>(null);

  const label = fill(st.card.label, { title });

  if (deleted) {
    return (
      <section
        ref={ref}
        aria-label={label}
        data-testid="scheduled-task-card"
        data-task-id={result.task.id}
        data-state="deleted"
        className={cn(
          "bg-card text-muted-foreground flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-sm",
          className,
        )}
      >
        <CalendarX2 className="size-4 shrink-0" aria-hidden />
        <span className="text-foreground font-medium">{title}</span>
        <span>{st.card.deleted}</span>
      </section>
    );
  }

  const timeZone = displayTimeZone(task);
  const status = presentTaskStatus(task);
  const StatusIcon = status.icon;
  const actions = availableActions(task, { createBlocked: false });
  const outcome = describeTaskOutcome(task, []);
  const schedule = describeTaskSchedule(task, locale, { time: st.time });
  const nextLine = nextRunLine(task, t, locale);
  const toolEnabled = feature.isLoading || feature.toolEnabled;
  const stops = stopLines(task, t, locale, {
    toolEnabled,
    reachedAt: outcome?.kind === "pausedByAgent" ? (outcome.at ?? null) : null,
  });

  // The footer already says trial runs don't count.
  const capLines = stops.secondary.filter(
    (line) => line !== st.stop.trialsDontCount,
  );

  // Pause and trigger errors are toasted by their hooks; resume handles
  // `limits_exhausted` inline, so it reports the rest itself.
  const reportResumeError = (error: Error) => {
    if (!shouldReportScheduledTaskError(error)) return;
    toastScheduledTaskError(
      t,
      st.errors.resume,
      describeScheduledTaskError(error, t, { locale, timeZone }),
    );
  };

  const doPause = () => {
    setLimitMessage(null);
    pause.mutate(task.id, {
      onSuccess: () => toast.success(st.feedback.paused),
    });
  };

  const doResume = () => {
    setLimitMessage(null);
    resume.mutate(
      { taskId: task.id },
      {
        onSuccess: (resumed) => {
          const next = resumed.next_run_at
            ? formatTaskTime(resumed.next_run_at, {
                timeZone: displayTimeZone(resumed),
                locale,
                labels: st.time,
              })
            : null;
          toast.success(
            next
              ? fill(st.feedback.resumed, { time: next })
              : st.feedback.resumedNoTime,
          );
        },
        onError: (error) => {
          if (
            error instanceof GatewayApiError &&
            error.code === "limits_exhausted"
          ) {
            setLimitMessage(
              describeScheduledTaskError(error, t, { locale, timeZone })
                .message,
            );
            return;
          }
          reportResumeError(error);
        },
      },
    );
  };

  const doTrigger = () => {
    if (triggerGuard.current) return;
    triggerGuard.current = true;
    trigger.mutate(task.id, {
      onSettled: () => {
        triggerGuard.current = false;
      },
      onSuccess: (outcome) => {
        if (outcome.outcome === "queued") {
          toast.info(
            outcome.existing
              ? st.feedback.alreadyQueued
              : st.feedback.trialQueued,
          );
          return;
        }
        setTrialThreadId(outcome.thread_id ?? "");
      },
    });
  };

  const runNowReason = blockReasonText(actions.runNow.reason, t);
  const pauseReason = blockReasonText(actions.pause.reason, t);
  const resumeReason = blockReasonText(actions.resume.reason, t);

  return (
    <div className={cn("flex w-full flex-col gap-2", className)}>
      <section
        ref={ref}
        aria-label={label}
        data-testid="scheduled-task-card"
        data-task-id={task.id}
        data-state={status.key}
        className="bg-card overflow-hidden rounded-lg border"
      >
        <header className="flex items-start gap-3 px-4 py-3">
          <span
            className="bg-muted grid size-9 shrink-0 place-items-center rounded-md"
            aria-hidden
          >
            <CalendarClock className="size-4" />
          </span>
          <p className="min-w-0 flex-1 self-center font-medium break-words">
            {title}
          </p>
          <span
            role="status"
            aria-live="polite"
            data-testid="scheduled-task-card-status"
            data-status={status.key}
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
              BADGE_TONE[status.tone],
            )}
          >
            <StatusIcon
              className={cn(
                "size-3.5",
                status.key === "running" && "animate-spin",
              )}
              aria-hidden
            />
            {taskStatusLabel(status.key, st.status)}
          </span>
        </header>

        <Row icon={<Repeat className="size-3.5" />} label={st.card.runs}>
          <p
            title={schedule.raw ?? undefined}
            data-testid="scheduled-task-card-schedule"
          >
            {schedule.text}
          </p>
          {nextLine && (
            <p
              className="text-muted-foreground text-xs"
              data-testid="scheduled-task-card-next"
            >
              {nextLine}
            </p>
          )}
        </Row>

        <Row icon={<Flag className="size-3.5" />} label={st.card.stopsWhen}>
          <p data-testid="scheduled-task-card-stops">
            {stops.primary}
            {stops.reached && (
              <span className="ml-1.5 font-medium text-sky-700 dark:text-sky-400">
                ✓ {stops.reached}
              </span>
            )}
          </p>
          {capLines.length > 0 && (
            <p className="text-muted-foreground text-xs">
              {capLines.join(" · ")}
            </p>
          )}
        </Row>

        {task.goal_objective && (
          <Row icon={<Target className="size-3.5" />} label={st.detail.goal}>
            <p className="line-clamp-3 break-words whitespace-pre-wrap">
              {task.goal_objective}
            </p>
          </Row>
        )}

        <Row
          icon={<MessageSquare className="size-3.5" />}
          label={st.card.results}
        >
          <p>
            {task.context_mode === "reuse_thread"
              ? st.card.resultsReuse
              : st.card.resultsFresh}
          </p>
        </Row>

        {!feature.isLoading && !feature.running && (
          <p
            className="border-t bg-amber-500/10 px-4 py-2 text-xs text-amber-800 dark:text-amber-300"
            data-testid="scheduled-task-card-scheduler-off"
          >
            {st.card.schedulerOff}
          </p>
        )}
        {query.isError && (
          <p className="text-muted-foreground border-t px-4 py-2 text-xs">
            {st.card.refreshFailed}
          </p>
        )}
        {limitMessage && (
          <p
            role="alert"
            className="border-t bg-amber-500/10 px-4 py-2 text-xs text-amber-800 dark:text-amber-300"
          >
            {limitMessage}{" "}
            <Link
              href={taskPagePath(task.id)}
              className="font-medium underline"
            >
              {st.actions.openTask}
            </Link>
          </p>
        )}
        {trialThreadId !== null && (
          <p
            role="status"
            className="border-t px-4 py-2 text-xs"
            data-testid="scheduled-task-card-trial"
          >
            {st.card.trialStarted}
            {trialThreadId && (
              <>
                <span aria-hidden> · </span>
                <Link
                  href={taskChatPath(trialThreadId, task)}
                  className="font-medium hover:underline"
                >
                  {st.actions.openChat}
                </Link>
              </>
            )}
          </p>
        )}

        <footer className="flex flex-wrap items-center gap-2 border-t px-4 py-3">
          <WithReason reason={runNowReason}>
            <Button
              size="sm"
              disabled={actions.runNow.disabled || trigger.isPending}
              onClick={doTrigger}
            >
              <Play aria-hidden />
              {st.actions.runNow}
            </Button>
          </WithReason>
          {actions.pause.visible && (
            <WithReason reason={pauseReason}>
              <Button
                variant="outline"
                size="sm"
                disabled={actions.pause.disabled || pause.isPending}
                onClick={doPause}
              >
                <Pause aria-hidden />
                {st.actions.pause}
              </Button>
            </WithReason>
          )}
          {actions.resume.visible && (
            <WithReason reason={resumeReason}>
              <Button
                variant="outline"
                size="sm"
                disabled={actions.resume.disabled || resume.isPending}
                onClick={doResume}
              >
                <RotateCcw aria-hidden />
                {st.actions.resume}
              </Button>
            </WithReason>
          )}
          <Button variant="ghost" size="sm" className="ml-auto" asChild>
            <Link href={taskPagePath(task.id)}>
              {st.actions.openTask}
              <ArrowUpRight aria-hidden />
            </Link>
          </Button>
        </footer>
      </section>
      <p className="text-muted-foreground text-xs">{st.card.footer}</p>
    </div>
  );
}
