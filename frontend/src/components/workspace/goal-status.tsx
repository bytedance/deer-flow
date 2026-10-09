"use client";

import {
  ChevronDownIcon,
  CircleCheckIcon,
  CircleHelpIcon,
  CircleStopIcon,
  ClockIcon,
  GaugeIcon,
  LoaderCircleIcon,
  MessageCircleQuestionIcon,
  PauseIcon,
  RefreshCwIcon,
  TargetIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";
import { useId, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads";
import { cn } from "@/lib/utils";

import {
  describeGoalBar,
  describeGoalBarCopy,
  goalBarAnnounceKey,
  type GoalBarChip,
  type GoalStopKey,
} from "./goal-status-helpers";
import { Tooltip } from "./tooltip";

const STOP_ICONS: Record<GoalStopKey, LucideIcon> = {
  limit: TriangleAlertIcon,
  autoOff: CircleStopIcon,
  noProgress: CircleStopIcon,
  tokenCapped: GaugeIcon,
  missingEvidence: CircleStopIcon,
  runFailed: TriangleAlertIcon,
  needsInputCard: MessageCircleQuestionIcon,
  needsInputReply: MessageCircleQuestionIcon,
  external: ClockIcon,
  unchecked: CircleHelpIcon,
  unknown: TriangleAlertIcon,
};

const CHIP_TONES: Record<GoalBarChip | "paused", string> = {
  stopped: "border-amber-500/40 text-amber-700 dark:text-amber-400",
  waitingForYou: "border-primary/40 text-primary",
  waiting: "text-muted-foreground",
  unchecked: "text-muted-foreground",
  paused: "text-muted-foreground",
};

/**
 * The goal bar above the composer: the active goal and why it stopped, or a
 * current "Goal met" record. Renders nothing without either.
 */
export function GoalStatus({
  className,
  goal,
  outcome = null,
  isRunning = false,
  hasOpenHumanInputCard = false,
}: {
  className?: string;
  goal: GoalState | null;
  outcome?: ThreadGoalOutcome | null;
  isRunning?: boolean;
  hasOpenHumanInputCard?: boolean;
}) {
  const { locale, t } = useI18n();
  const bar = t.inputBox.goalBar;
  const view = describeGoalBar({
    goal,
    outcome,
    isRunning,
    hasOpenHumanInputCard,
  });
  const copy = describeGoalBarCopy(view, t);
  const announceKey = goalBarAnnounceKey(view);
  const announcementText = copy?.announcement ?? "";
  const [announced, setAnnounced] = useState({
    key: announceKey,
    locale,
    text: announcementText,
  });
  const [detailsOpen, setDetailsOpen] = useState(false);
  if (announced.key !== announceKey || announced.locale !== locale) {
    // Re-announce on a state change only, never on a streaming re-render; a
    // language switch refreshes the text once. A new state starts collapsed.
    if (announced.key !== announceKey) {
      setDetailsOpen(false);
    }
    setAnnounced({ key: announceKey, locale, text: announcementText });
  }
  const detailsId = useId();
  const assumptionId = useId();

  if (!copy) {
    return null;
  }
  const met = view.kind === "met";
  const hasDetails = view.kind === "stopped" || view.kind === "paused" || met;
  const note = "note" in view ? view.note : null;
  const rawCode = "rawCode" in view ? view.rawCode : null;
  const reliedOnAssumption = met && view.reliedOnAssumption;
  const chipStyle =
    view.kind === "stopped"
      ? { Icon: STOP_ICONS[view.stop], tone: CHIP_TONES[view.chip] }
      : view.kind === "paused"
        ? { Icon: PauseIcon, tone: CHIP_TONES.paused }
        : null;

  return (
    <section
      aria-label={bar.regionLabel}
      className={cn(
        "bg-background/90 border-border flex min-h-10 w-full flex-col justify-center gap-1 rounded-t-xl border border-b-0 px-4 py-2 text-sm shadow-sm backdrop-blur-sm",
        className,
      )}
      data-testid="goal-status"
      data-goal-state={view.kind}
    >
      <div className="flex items-center gap-3">
        <span
          aria-hidden
          className={cn(
            "flex shrink-0 motion-safe:transition-colors motion-safe:duration-300",
            met ? "text-emerald-600 dark:text-emerald-400" : "text-primary",
          )}
        >
          {met ? (
            <CircleCheckIcon className="size-4" />
          ) : (
            <TargetIcon className="size-4" />
          )}
        </span>
        <div className="min-w-0 flex-1 truncate">
          <span
            className={cn(
              "mr-2 motion-safe:transition-colors motion-safe:duration-300",
              met
                ? "font-medium text-emerald-700 dark:text-emerald-400"
                : "text-muted-foreground",
            )}
          >
            {copy.label}
          </span>
          <span className="font-medium">{copy.objective}</span>
        </div>
        {view.kind === "inProgress" && (
          <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs">
            <LoaderCircleIcon
              aria-hidden
              className="size-3 motion-safe:animate-spin"
            />
            {copy.chip}
          </span>
        )}
        {view.kind === "continuing" && (
          <Tooltip
            content={t.inputBox.goalContinuationTooltip
              .replace("{count}", String(view.count))
              .replace("{max}", String(view.max))}
          >
            <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs tabular-nums">
              <RefreshCwIcon aria-hidden className="size-3" />
              {copy.chip}
            </span>
          </Tooltip>
        )}
        {chipStyle && (
          <span
            className={cn(
              "flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-px text-[11px]",
              chipStyle.tone,
            )}
            data-testid="goal-status-chip"
          >
            <chipStyle.Icon aria-hidden className="size-3" />
            {copy.chip}
          </span>
        )}
        {copy.meta && (
          <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
            {copy.meta}
          </span>
        )}
        {reliedOnAssumption && (
          <Tooltip content={bar.assumptionTooltip}>
            <span
              tabIndex={0}
              aria-describedby={assumptionId}
              className="text-muted-foreground shrink-0 rounded-full border px-1.5 py-px text-[11px]"
              data-testid="goal-status-assumption"
            >
              {t.scheduledTasks.goal.assumptionBadge}
            </span>
          </Tooltip>
        )}
        {hasDetails && (
          <button
            type="button"
            aria-expanded={detailsOpen}
            aria-controls={detailsId}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex shrink-0 items-center gap-0.5 rounded text-xs outline-none focus-visible:ring-[3px]"
            onClick={() => setDetailsOpen((open) => !open)}
          >
            {detailsOpen ? bar.hideDetails : bar.details}
            <ChevronDownIcon
              aria-hidden
              className={cn(
                "size-3 motion-safe:transition-transform",
                detailsOpen && "rotate-180",
              )}
            />
          </button>
        )}
      </div>
      {copy.detail && (
        <p
          className="text-muted-foreground text-xs"
          data-testid="goal-status-detail"
        >
          {copy.detail}
        </p>
      )}
      {reliedOnAssumption && (
        <span id={assumptionId} className="sr-only">
          {bar.assumptionTooltip}
        </span>
      )}
      {hasDetails && (
        <div
          id={detailsId}
          hidden={!detailsOpen}
          data-testid="goal-status-details"
        >
          {detailsOpen && (
            <div className="bg-muted/50 flex flex-col gap-1 rounded-md p-2 text-xs break-words whitespace-pre-wrap">
              <p>
                <span className="text-muted-foreground mr-1">
                  {t.inputBox.goalLabel}
                </span>
                {copy.objective}
              </p>
              {reliedOnAssumption && <p>{bar.assumptionTooltip}</p>}
              {note && (
                <p>
                  <span className="text-muted-foreground mr-1">
                    {bar.noteLabel}
                  </span>
                  <span dir="auto" data-testid="goal-status-note">
                    {note}
                  </span>
                </p>
              )}
              {rawCode && (
                <p>
                  <span className="text-muted-foreground mr-1">
                    {bar.codeLabel}
                  </span>
                  <code>{rawCode}</code>
                </p>
              )}
            </div>
          )}
        </div>
      )}
      <p role="status" className="sr-only">
        {announced.text}
      </p>
    </section>
  );
}
