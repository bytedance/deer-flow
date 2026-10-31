"use client";

import {
  Bot,
  CircleCheck,
  CircleX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { briefReason, formatTaskTime } from "@/core/scheduled-tasks/format";
import type { TaskOutcome } from "@/core/scheduled-tasks/goal-outcome";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

import { fill, taskChatPath } from "./shared";

type Tone = "info" | "warn" | "neutral" | "danger";

const TONE: Record<Tone, string> = {
  info: "border-sky-500/40 bg-sky-500/5 [&_svg.notice-icon]:text-sky-600",
  warn: "border-amber-500/50 bg-amber-500/10 [&_svg.notice-icon]:text-amber-600",
  neutral:
    "border-border bg-muted/40 [&_svg.notice-icon]:text-muted-foreground",
  danger:
    "border-destructive/40 bg-destructive/5 [&_svg.notice-icon]:text-destructive",
};

function Notice({
  tone,
  icon: Icon,
  title,
  body,
  actions,
  kind,
}: {
  tone: Tone;
  icon: LucideIcon;
  title: string;
  body?: string;
  actions?: ReactNode;
  kind: TaskOutcome["kind"];
}) {
  return (
    <section
      className={cn(
        "grid grid-cols-[16px_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg border px-4 py-3 text-sm",
        TONE[tone],
      )}
      aria-label={title}
      data-testid="scheduled-task-outcome"
      data-outcome={kind}
    >
      <Icon className="notice-icon mt-0.5 size-4" aria-hidden />
      <p className="font-medium">{title}</p>
      {body && (
        <p className="text-muted-foreground col-start-2 leading-relaxed">
          {body}
        </p>
      )}
      {actions && (
        <div className="col-start-2 mt-1 flex flex-wrap gap-2">{actions}</div>
      )}
    </section>
  );
}

/**
 * Why a task stopped running (T2), derived from task and run state: paused
 * by the agent, auto-paused after three missed goals, finished by its safety
 * cap, or a one-time task that ran or failed.
 */
export function TaskOutcomeNotice({
  outcome,
  task,
  timeZone,
  onEditGoal,
  onResume,
  onExtend,
  resumeDisabled,
}: {
  outcome: TaskOutcome;
  task: Pick<ScheduledTask, "assistant_id">;
  timeZone: string;
  onEditGoal: () => void;
  onResume: () => void;
  onExtend: () => void;
  resumeDisabled: boolean;
}) {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const time = (iso: string) =>
    formatTaskTime(iso, { timeZone, locale, labels: st.time });
  // Mid-sentence: "yesterday 20:22", not "Yesterday 20:22".
  const inlineTime = (iso: string) =>
    formatTaskTime(iso, { timeZone, locale, labels: st.timeInline });

  switch (outcome.kind) {
    case "pausedByAgent":
      return (
        <Notice
          kind={outcome.kind}
          tone="info"
          icon={Bot}
          title={st.notice.pausedByAgentTitle}
          body={
            outcome.at
              ? fill(st.notice.pausedByAgentBody, {
                  time: inlineTime(outcome.at),
                })
              : undefined
          }
          actions={
            outcome.runThreadId ? (
              <Button variant="outline" size="sm" asChild>
                <Link href={taskChatPath(outcome.runThreadId, task)}>
                  {st.notice.seeThatRun}
                </Link>
              </Button>
            ) : undefined
          }
        />
      );
    case "autoPaused": {
      const reason = outcome.latestReasonKey
        ? st.goal.reasons[outcome.latestReasonKey]
        : outcome.latestSummary
          ? briefReason(outcome.latestSummary)
          : st.runStatus.unmet;
      return (
        <Notice
          kind={outcome.kind}
          tone="warn"
          icon={TriangleAlert}
          title={st.notice.autoPausedTitle}
          body={fill(st.notice.autoPausedBody, { reason })}
          actions={
            <>
              <Button variant="outline" size="sm" onClick={onEditGoal}>
                {st.notice.editGoal}
              </Button>
              {outcome.latestThreadId && (
                <Button variant="outline" size="sm" asChild>
                  <Link href={taskChatPath(outcome.latestThreadId, task)}>
                    {st.notice.openLatestRun}
                  </Link>
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={onResume}
                disabled={resumeDisabled}
              >
                {st.notice.resumeAnyway}
              </Button>
            </>
          }
        />
      );
    }
    case "limitReached":
    case "endReached":
      return (
        <Notice
          kind={outcome.kind}
          tone="neutral"
          icon={CircleCheck}
          title={
            outcome.kind === "limitReached"
              ? fill(st.notice.limitTitle, { max: outcome.max })
              : fill(st.notice.endTitle, { time: time(outcome.endAt) })
          }
          body={
            outcome.kind === "limitReached"
              ? st.notice.limitBodyRuns
              : st.notice.limitBodyEnd
          }
          actions={
            <Button
              variant="outline"
              size="sm"
              onClick={onExtend}
              disabled={resumeDisabled}
            >
              {st.notice.extendLimit}
            </Button>
          }
        />
      );
    case "onceFinished":
      return (
        <Notice
          kind={outcome.kind}
          tone="neutral"
          icon={CircleCheck}
          title={st.notice.onceFinished}
        />
      );
    case "onceFailed":
      return (
        <Notice
          kind={outcome.kind}
          tone="danger"
          icon={CircleX}
          title={st.notice.onceFailed}
        />
      );
  }
}
