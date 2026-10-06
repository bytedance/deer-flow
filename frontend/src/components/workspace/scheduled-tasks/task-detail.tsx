"use client";

import {
  Copy,
  Info,
  MessageSquare,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Trash2,
  CopyPlus,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { GatewayApiError } from "@/core/api/errors";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { useModels } from "@/core/models/hooks";
import { availableActions } from "@/core/scheduled-tasks/actions";
import { describeTaskSchedule } from "@/core/scheduled-tasks/cron";
import { toastScheduledTaskError } from "@/core/scheduled-tasks/error-toast";
import {
  describeScheduledTaskError,
  shouldReportScheduledTaskError,
} from "@/core/scheduled-tasks/errors";
import {
  displayTimeZone,
  formatTaskTime,
  formatWithViewerTime,
} from "@/core/scheduled-tasks/format";
import { describeTaskOutcome } from "@/core/scheduled-tasks/goal-outcome";
import {
  usePauseScheduledTask,
  useResumeScheduledTask,
  useTriggerScheduledTask,
} from "@/core/scheduled-tasks/hooks";
import { useScheduledTaskRunHistory } from "@/core/scheduled-tasks/run-history";
import {
  presentTaskStatus,
  taskStatusLabel,
} from "@/core/scheduled-tasks/status";
import { isTaskBusy, type ScheduledTask } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

import { DeleteTaskDialog } from "./delete-task-dialog";
import { RenewLimitsDialog } from "./renew-limits-dialog";
import { RunRow } from "./run-row";
import {
  blockReasonText,
  fill,
  isDefaultAgent,
  taskChatPath,
  WithReason,
} from "./shared";
import { TaskOutcomeNotice } from "./task-outcome-notice";

const BADGE_TONE: Record<string, string> = {
  neutral: "bg-muted text-muted-foreground",
  ok: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  info: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  warn: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
  danger: "bg-destructive/10 text-destructive",
};

const TERMINAL: ReadonlySet<ScheduledTask["status"]> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

/** The "Runs" status line: next run, running now, paused or finished. */
export function nextRunLine(
  task: ScheduledTask,
  t: Translations,
  locale: string,
  now: Date = new Date(),
): string | null {
  const st = t.scheduledTasks;
  const at = (iso: string) =>
    formatWithViewerTime(iso, displayTimeZone(task), {
      locale,
      labels: st.time,
      now,
    });
  if (isTaskBusy(task)) {
    return st.list.runningNow;
  }
  if (task.active_run_status === "queued") {
    return st.actions.alreadyQueued;
  }
  if (TERMINAL.has(task.status)) {
    return st.detail.noMoreRuns;
  }
  const future =
    task.next_run_at && Date.parse(task.next_run_at) > now.getTime()
      ? task.next_run_at
      : null;
  if (task.status === "paused") {
    return future
      ? `${st.detail.notWhilePaused} · ${fill(st.detail.ifResumed, { time: at(future) })}`
      : st.detail.notWhilePaused;
  }
  if (!task.next_run_at) {
    return null;
  }
  const neverRan = task.run_count === 0 && !task.last_run_at;
  return fill(neverRan ? st.detail.firstRun : st.detail.next, {
    time: at(task.next_run_at),
  });
}

/**
 * The "Stops when" lines: the user's stop condition (with when it was met),
 * else what ends the task; then the safety cap with runs used.
 */
export function stopLines(
  task: ScheduledTask,
  t: Translations,
  locale: string,
  {
    toolEnabled,
    reachedAt,
  }: { toolEnabled: boolean; reachedAt: string | null },
): { primary: string; reached: string | null; secondary: string[] } {
  const st = t.scheduledTasks;
  const tz = displayTimeZone(task);
  const at = (iso: string) =>
    formatTaskTime(iso, { timeZone: tz, locale, labels: st.time });
  const used = task.automatic_runs_used ?? 0;
  const max = task.max_runs ?? null;
  const end = task.end_at ?? null;
  const condition =
    toolEnabled && task.stop_condition?.trim() ? task.stop_condition : null;

  const capLine = (): string | null => {
    if (max != null && end) {
      return fill(st.stop.capBoth, { max, time: at(end) });
    }
    if (max != null) {
      return used > 0
        ? fill(st.stop.capRunsUsed, { used, max })
        : fill(st.stop.capRuns, { max });
    }
    if (end) {
      return fill(st.stop.capEnd, { time: at(end) });
    }
    return null;
  };

  const secondary: string[] = [];
  let primary: string;
  if (condition) {
    primary = fill(st.stop.pausesItself, { condition });
    const cap = capLine();
    if (cap) secondary.push(cap);
  } else if (max != null || end) {
    primary =
      max != null && end
        ? fill(st.stop.capBoth, { max, time: at(end) })
        : max != null
          ? fill(st.stop.afterRuns, { max })
          : fill(st.stop.atTime, { time: at(end ?? "") });
    if (max != null && used > 0) {
      secondary.push(fill(st.stop.capRunsUsed, { used, max }));
    }
  } else {
    primary = st.stop.noRule;
  }
  if (max != null) {
    secondary.push(st.stop.trialsDontCount);
  }
  if (task.goal_objective) {
    secondary.push(st.stop.autoPauseRule);
  }
  return {
    primary,
    reached:
      condition && reachedAt
        ? fill(st.stop.reached, {
            time: formatTaskTime(reachedAt, {
              timeZone: tz,
              locale,
              labels: st.timeInline,
            }),
          })
        : null,
    secondary,
  };
}

function Section({
  label,
  aside,
  children,
}: {
  label: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 gap-1 border-t py-3 text-sm sm:grid-cols-[6.5rem_minmax(0,1fr)] sm:gap-3">
      <div className="text-muted-foreground flex flex-col gap-0.5">
        <span>{label}</span>
        {aside}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function TaskDetail({
  task,
  toolEnabled,
  createBlocked,
  onEdit,
  onDuplicate,
  onDeleted,
}: {
  task: ScheduledTask;
  toolEnabled: boolean;
  createBlocked: boolean;
  onEdit: (task: ScheduledTask, focus?: "goal") => void;
  onDuplicate: (task: ScheduledTask) => void;
  onDeleted?: (task: ScheduledTask) => void;
}) {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const router = useRouter();
  const { tokenUsageEnabled } = useModels();
  const history = useScheduledTaskRunHistory(task.id);
  const runs = history.data ?? [];
  const timeZone = displayTimeZone(task);
  const status = presentTaskStatus(task);
  const StatusIcon = status.icon;
  const actions = availableActions(task, { createBlocked });
  const outcome = describeTaskOutcome(task, runs);
  const schedule = describeTaskSchedule(task, locale, { time: st.time });
  const nextLine = nextRunLine(task, t, locale);
  const stops = stopLines(task, t, locale, {
    toolEnabled,
    reachedAt: outcome?.kind === "pausedByAgent" ? (outcome.at ?? null) : null,
  });

  const pause = usePauseScheduledTask();
  const resume = useResumeScheduledTask({ toastOnError: false });
  const trigger = useTriggerScheduledTask();
  const triggerGuard = useRef(false);
  const [renewOpen, setRenewOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [promptExpanded, setPromptExpanded] = useState(false);
  const promptRef = useRef<HTMLParagraphElement>(null);
  const promptClamped = useClampedOverflow(
    promptRef,
    task.prompt,
    !promptExpanded,
  );

  const resumedToast = (resumed: ScheduledTask) => {
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
  };

  const doResume = () => {
    resume.mutate(
      { taskId: task.id },
      {
        onSuccess: resumedToast,
        onError: (error) => {
          if (
            error instanceof GatewayApiError &&
            error.code === "limits_exhausted"
          ) {
            setRenewOpen(true);
            return;
          }
          if (!shouldReportScheduledTaskError(error)) return;
          toastScheduledTaskError(
            t,
            st.errors.resume,
            describeScheduledTaskError(error, t, { locale, timeZone }),
          );
        },
      },
    );
  };

  const doPause = () =>
    pause.mutate(task.id, {
      onSuccess: () => toast.success(st.feedback.paused),
    });

  const doTrigger = () => {
    if (triggerGuard.current) return;
    triggerGuard.current = true;
    trigger.mutate(task.id, {
      onSettled: () => {
        triggerGuard.current = false;
      },
      onSuccess: (result) => {
        if (result.outcome === "queued") {
          toast.info(
            result.existing
              ? st.feedback.alreadyQueued
              : st.feedback.trialQueued,
          );
          return;
        }
        const threadId = result.thread_id;
        toast.success(
          st.feedback.trialStarted,
          threadId
            ? {
                action: {
                  label: st.actions.openChat,
                  onClick: () => router.push(taskChatPath(threadId, task)),
                },
              }
            : undefined,
        );
      },
    });
  };

  const copyTaskId = () => {
    void navigator.clipboard
      ?.writeText(task.id)
      .then(() => toast.success(st.detail.copied))
      .catch(() => undefined);
  };

  const runNowReason = blockReasonText(actions.runNow.reason, t);
  const editReason = blockReasonText(actions.edit.reason, t);
  const pauseReason = blockReasonText(actions.pause.reason, t);
  const resumeReason = blockReasonText(actions.resume.reason, t);

  return (
    <article
      className="bg-card flex min-w-0 flex-col rounded-lg border p-4 sm:p-5"
      data-testid="scheduled-task-detail"
      data-task-id={task.id}
      aria-labelledby={`scheduled-task-title-${task.id}`}
    >
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2 pb-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <h2
            id={`scheduled-task-title-${task.id}`}
            className="min-w-0 text-lg font-semibold break-words"
          >
            {task.title}
          </h2>
          <span
            role="status"
            aria-live="polite"
            data-testid="scheduled-task-status"
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
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
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
          <WithReason reason={runNowReason}>
            <Button
              variant="outline"
              size="sm"
              disabled={actions.runNow.disabled || trigger.isPending}
              onClick={doTrigger}
            >
              <Play aria-hidden />
              {st.actions.runNow}
            </Button>
          </WithReason>
          <WithReason reason={editReason}>
            <Button
              variant="outline"
              size="sm"
              disabled={actions.edit.disabled}
              onClick={() => onEdit(task)}
            >
              <Pencil aria-hidden />
              {st.actions.edit}
            </Button>
          </WithReason>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={st.detail.moreActions}
              >
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <MenuItemWithReason
                reason={blockReasonText(actions.duplicate.reason, t)}
              >
                <DropdownMenuItem
                  disabled={actions.duplicate.disabled}
                  onSelect={() => onDuplicate(task)}
                >
                  <CopyPlus aria-hidden />
                  {st.actions.duplicate}
                </DropdownMenuItem>
              </MenuItemWithReason>
              <DropdownMenuItem onSelect={copyTaskId}>
                <Copy aria-hidden />
                {st.detail.copyTaskId}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <MenuItemWithReason
                reason={blockReasonText(actions.delete.reason, t)}
              >
                <DropdownMenuItem
                  variant="destructive"
                  disabled={actions.delete.disabled}
                  onSelect={() => setDeleteOpen(true)}
                >
                  <Trash2 aria-hidden />
                  {st.actions.delete}
                </DropdownMenuItem>
              </MenuItemWithReason>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {outcome && (
        <div className="pb-3">
          <TaskOutcomeNotice
            outcome={outcome}
            task={task}
            timeZone={timeZone}
            onEditGoal={() => onEdit(task, "goal")}
            onResume={doResume}
            onExtend={() => setRenewOpen(true)}
            resumeDisabled={actions.resume.disabled || resume.isPending}
          />
        </div>
      )}

      <Section label={st.detail.runs}>
        <p title={schedule.raw ?? undefined}>{schedule.text}</p>
        {nextLine && (
          <p
            className="text-muted-foreground"
            data-testid="scheduled-task-next"
          >
            {nextLine}
          </p>
        )}
      </Section>

      <Section label={st.detail.stopsWhen}>
        <p data-testid="scheduled-task-stops-when">
          {stops.primary}
          {stops.reached && (
            <span className="ml-1.5 font-medium text-sky-700 dark:text-sky-400">
              ✓ {stops.reached}
            </span>
          )}
        </p>
        {stops.secondary.map((line) => (
          <p key={line} className="text-muted-foreground text-xs">
            {line}
          </p>
        ))}
      </Section>

      {task.goal_objective && (
        <Section
          label={st.detail.goal}
          aside={
            <Tooltip delayDuration={200}>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="w-fit"
                  aria-label={st.stop.goalTooltip}
                >
                  <Info className="size-3.5" aria-hidden />
                </button>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                {st.stop.goalTooltip}
              </TooltipContent>
            </Tooltip>
          }
        >
          <p
            className="break-words whitespace-pre-wrap"
            data-testid="scheduled-task-goal"
          >
            {task.goal_objective}
          </p>
        </Section>
      )}

      <Section label={st.detail.does}>
        <p
          ref={promptRef}
          className={cn(
            "break-words whitespace-pre-wrap",
            !promptExpanded && "line-clamp-2",
          )}
          data-testid="scheduled-task-prompt"
        >
          {task.prompt}
        </p>
        {(promptExpanded || promptClamped) && (
          <button
            type="button"
            className="text-muted-foreground mt-1 text-xs hover:underline"
            aria-expanded={promptExpanded}
            onClick={() => setPromptExpanded((value) => !value)}
          >
            {promptExpanded ? st.detail.showLess : st.detail.showAll}
          </button>
        )}
        <div className="text-muted-foreground mt-1 flex flex-wrap gap-x-3 text-xs">
          {!isDefaultAgent(task.assistant_id) && (
            <span>
              {fill(st.detail.agentLine, { name: task.assistant_id ?? "" })}
            </span>
          )}
          {task.context_mode === "reuse_thread" ? (
            <span className="inline-flex gap-1">
              {st.detail.contextReuse}
              {task.thread_id && (
                <>
                  <span aria-hidden>·</span>
                  <Link
                    href={taskChatPath(task.thread_id, task)}
                    className="text-foreground hover:underline"
                  >
                    {st.detail.openChat}
                  </Link>
                </>
              )}
            </span>
          ) : (
            <span>{st.detail.contextFresh}</span>
          )}
        </div>
      </Section>

      {(task.standing_notes ?? []).length > 0 && (
        <Section label={st.detail.notes}>
          <ul
            className="list-disc space-y-0.5 pl-4"
            data-testid="scheduled-task-notes"
          >
            {(task.standing_notes ?? []).map((note, index) => (
              <li key={index} className="break-words">
                {note}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section
        label={st.detail.history}
        aside={
          // A count only when it is the whole history: a page holds at most
          // one page of runs, so "50 runs" on page 1 would be wrong.
          !history.isPending &&
          !history.isError &&
          history.page === 0 &&
          !history.hasOlder ? (
            <span className="text-xs" data-testid="scheduled-task-runs">
              {fill(
                runs.length === 1
                  ? st.detail.runsCountOne
                  : st.detail.runsCount,
                { count: runs.length },
              )}
            </span>
          ) : null
        }
      >
        {history.isPending && (
          <p role="status" className="text-muted-foreground">
            {st.history.loading}
          </p>
        )}
        {history.isError && (
          <div role="alert" className="flex flex-col items-start gap-2">
            <p>{st.history.loadFailed}</p>
            <Button
              variant="outline"
              size="sm"
              disabled={history.isFetching}
              onClick={() => void history.refetch()}
            >
              {st.history.retry}
            </Button>
          </div>
        )}
        {!history.isPending && !history.isError && runs.length === 0 && (
          <p className="text-muted-foreground">{st.detail.noRuns}</p>
        )}
        {runs.length > 0 && (
          <ol
            className="divide-y"
            aria-label={st.history.listLabel}
            data-testid="scheduled-task-run-list"
          >
            {runs.map((run) => (
              <RunRow
                key={run.id}
                run={run}
                task={task}
                timeZone={timeZone}
                tokenUsageEnabled={tokenUsageEnabled}
              />
            ))}
          </ol>
        )}
        {(history.page > 0 || history.hasOlder) && (
          <nav
            aria-label={st.history.navigation}
            className="mt-2 flex flex-wrap items-center gap-2"
          >
            <Button
              variant="outline"
              size="sm"
              disabled={history.page === 0 || history.isFetching}
              onClick={history.newer}
            >
              {st.history.newer}
            </Button>
            <span className="text-muted-foreground text-xs">
              {fill(st.history.page, { page: history.page + 1 })}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={!history.hasOlder || history.isFetching}
              onClick={history.older}
            >
              {st.history.older}
            </Button>
            {history.page > 0 && (
              <Button variant="outline" size="sm" onClick={history.latest}>
                {st.history.latest}
              </Button>
            )}
          </nav>
        )}
        {history.page > 0 && (
          <p className="text-muted-foreground mt-1 text-xs">
            {st.history.paused}
          </p>
        )}
      </Section>

      <footer className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-3 text-xs">
        {task.origin_thread_id && (
          <span className="inline-flex items-center gap-1">
            <MessageSquare className="size-3.5" aria-hidden />
            {st.detail.createdInChat}
            <span aria-hidden>·</span>
            <Link
              href={taskChatPath(task.origin_thread_id, task)}
              className="text-foreground hover:underline"
              data-testid="scheduled-task-origin-link"
            >
              {st.detail.openChat}
            </Link>
          </span>
        )}
        <button
          type="button"
          className="ml-auto hover:underline"
          onClick={copyTaskId}
        >
          {st.detail.copyTaskId}
        </button>
      </footer>

      {renewOpen && (
        <RenewLimitsDialog
          task={task}
          open={renewOpen}
          onOpenChange={setRenewOpen}
          onResumed={resumedToast}
        />
      )}
      <DeleteTaskDialog
        task={task}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onDeleted={() => onDeleted?.(task)}
      />
    </article>
  );
}

/**
 * Whether a line-clamped element hides text, measured after layout and on
 * resize (a prompt of 60–180 characters already wraps past two lines on a
 * phone). Without layout (a hidden element, or a DOM without it) it falls
 * back to a length guess.
 */
function useClampedOverflow(
  ref: RefObject<HTMLElement | null>,
  text: string,
  clamped: boolean,
): boolean {
  const guess = text.length > 180 || text.split("\n").length > 2;
  const [overflows, setOverflows] = useState(guess);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !clamped) {
      return;
    }
    const measure = () => {
      setOverflows(
        element.clientHeight > 0
          ? element.scrollHeight > element.clientHeight + 1
          : guess,
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, text, clamped, guess]);
  return overflows;
}

/** A disabled menu item gets no pointer events; the tooltip hangs on a wrapper. */
function MenuItemWithReason({
  reason,
  children,
}: {
  reason: string | null;
  children: ReactNode;
}) {
  if (!reason) {
    return <>{children}</>;
  }
  return (
    <Tooltip delayDuration={200}>
      <TooltipTrigger asChild>
        <div data-disabled-reason={reason}>{children}</div>
      </TooltipTrigger>
      <TooltipContent side="left">{reason}</TooltipContent>
    </Tooltip>
  );
}
