"use client";

import {
  Ban,
  CircleCheck,
  CircleDashed,
  CirclePause,
  CircleX,
  ChevronRight,
  Clock,
  CircleHelp,
  LoaderCircle,
  Play,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { formatTokenCount } from "@/core/messages/usage";
import { formatTaskTime } from "@/core/scheduled-tasks/format";
import {
  describeGoalOutcome,
  requestedScheduleStop,
  type GoalOutcome,
} from "@/core/scheduled-tasks/goal-outcome";
import { describeRunError } from "@/core/scheduled-tasks/run-error";
import { isActiveRun } from "@/core/scheduled-tasks/run-history";
import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

import { fill, taskChatPath } from "./shared";

/** "Run 3", "Trial run", or "Scheduled run" for a scheduled row that never launched. */
export function runLabel(
  run: Pick<ScheduledTaskRun, "trigger" | "run_number">,
  t: Translations,
): string {
  const st = t.scheduledTasks;
  if (run.trigger === "manual") {
    return st.runTrigger.manual;
  }
  return typeof run.run_number === "number"
    ? fill(st.history.runNumber, { n: run.run_number })
    : st.runTrigger.scheduled;
}

function goalText(goal: GoalOutcome, t: Translations): string {
  const st = t.scheduledTasks;
  if (goal.kind === "met") {
    return st.goal.met;
  }
  if (goal.kind === "unchecked") {
    return st.goal.unchecked;
  }
  return st.runStatus.unmet;
}

/** The goal's reason as a readable line, when the host gave a known code. */
function goalReason(goal: GoalOutcome | null, t: Translations): string | null {
  if (!goal || goal.kind === "met" || !goal.reasonKey) {
    return null;
  }
  return t.scheduledTasks.goal.reasons[goal.reasonKey];
}

function runIcon(
  run: ScheduledTaskRun,
  goal: GoalOutcome | null,
): { icon: LucideIcon; className: string } {
  if (isActiveRun(run)) {
    return run.status === "queued"
      ? { icon: Clock, className: "text-muted-foreground" }
      : { icon: LoaderCircle, className: "animate-spin text-sky-600" };
  }
  if (requestedScheduleStop(run)) {
    return { icon: CirclePause, className: "text-sky-600" };
  }
  if (goal?.kind === "unmet") {
    return { icon: TriangleAlert, className: "text-amber-600" };
  }
  if (goal?.kind === "unchecked") {
    return { icon: CircleHelp, className: "text-muted-foreground" };
  }
  switch (run.status) {
    case "failed":
      return { icon: CircleX, className: "text-destructive" };
    case "interrupted":
      return { icon: Ban, className: "text-amber-600" };
    case "skipped":
      return { icon: CircleDashed, className: "text-muted-foreground" };
    default:
      return run.trigger === "manual"
        ? { icon: Play, className: "text-muted-foreground" }
        : { icon: CircleCheck, className: "text-emerald-600" };
  }
}

export function RunRow({
  run,
  task,
  timeZone,
  tokenUsageEnabled,
}: {
  run: ScheduledTaskRun;
  task: Pick<ScheduledTask, "assistant_id">;
  timeZone: string;
  tokenUsageEnabled: boolean;
}) {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const goal = describeGoalOutcome(run);
  const runError = goal ? null : describeRunError(run);
  const { icon: Icon, className: iconClass } = runIcon(run, goal);

  // One readable line: the agent's own summary first (it follows the user's
  // language), else the goal reason, else the host's note, else the state.
  const summary = run.summary?.trim() ? run.summary.trim() : null;
  const line =
    summary ??
    goalReason(goal, t) ??
    (runError ? st.runErrors[runError.key] : null) ??
    (isActiveRun(run)
      ? // A queued occurrence is waiting for an execution slot (global or
        // per-owner cap, or an older run of the same chat).
        run.status === "queued"
        ? st.history.waitingForSlot
        : st.runStatus[run.status]
      : null);

  // Raw text only behind "Details": a stored error the UI cannot word
  // (including an unknown goal code) and the evaluator's free-text reason.
  const rawError =
    runError?.raw ??
    (goal && goal.kind !== "met" && !goal.reasonKey ? goal.code : null);
  const evaluatorReason = run.goal_verdict?.reason?.trim()
    ? run.goal_verdict.reason.trim()
    : null;
  const continuations = run.goal_verdict?.continuations ?? 0;
  const time = formatTaskTime(run.scheduled_for, {
    timeZone,
    locale,
    labels: st.time,
  });

  return (
    <li
      className="grid grid-cols-[20px_minmax(0,1fr)] gap-x-2 gap-y-0.5 py-2 text-sm"
      data-testid="scheduled-run-row"
      data-run-id={run.run_id ?? undefined}
      data-task-run-id={run.id}
    >
      <Icon className={cn("mt-0.5 size-4", iconClass)} aria-hidden />
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-medium">{runLabel(run, t)}</span>
          <span className="text-muted-foreground text-xs">{time}</span>
          {goal && (
            <span
              className={cn(
                "rounded-full border px-1.5 py-px text-[11px]",
                goal.kind === "met" &&
                  "border-emerald-500/40 text-emerald-700 dark:text-emerald-400",
                goal.kind === "unmet" &&
                  "border-amber-500/40 text-amber-700 dark:text-amber-400",
                goal.kind === "unchecked" && "text-muted-foreground",
              )}
              data-testid="scheduled-run-goal"
            >
              {goalText(goal, t)}
            </span>
          )}
          {goal?.kind === "met" && goal.reliedOnAssumption && (
            <Tooltip content={st.goal.assumptionTooltip}>
              <span
                tabIndex={0}
                className="text-muted-foreground rounded-full border px-1.5 py-px text-[11px]"
                data-testid="scheduled-run-assumption"
              >
                {st.goal.assumptionBadge}
              </span>
            </Tooltip>
          )}
          <span className="ml-auto flex items-center gap-3">
            {tokenUsageEnabled && typeof run.total_tokens === "number" && (
              <span className="text-muted-foreground text-xs">
                {fill(st.history.tokens, {
                  count: formatTokenCount(run.total_tokens),
                })}
              </span>
            )}
            {run.run_id && run.thread_id && (
              <Link
                href={taskChatPath(run.thread_id, task)}
                className="inline-flex items-center text-xs font-medium hover:underline"
              >
                {st.actions.openChat}
                <ChevronRight className="size-3.5" aria-hidden />
              </Link>
            )}
          </span>
        </div>
        {line && (
          <p className="text-muted-foreground line-clamp-2 break-words">
            {line}
          </p>
        )}
        {requestedScheduleStop(run) && (
          <p
            className="text-xs text-sky-700 dark:text-sky-400"
            data-testid="scheduled-run-stop-requested"
          >
            {st.goal.stopRequested}
          </p>
        )}
        {continuations > 0 && (
          <p className="text-muted-foreground text-xs">
            {fill(st.history.continuations, { n: continuations })}
          </p>
        )}
        {(rawError != null || evaluatorReason != null) && (
          <details className="text-xs">
            <summary className="text-muted-foreground w-fit cursor-pointer select-none">
              {st.history.details}
            </summary>
            <div className="bg-muted/50 mt-1 flex flex-col gap-1 rounded-md p-2 break-words whitespace-pre-wrap">
              {rawError && (
                <p data-testid="scheduled-run-raw-error">{rawError}</p>
              )}
              {evaluatorReason && <p>{evaluatorReason}</p>}
            </div>
          </details>
        )}
      </div>
    </li>
  );
}
