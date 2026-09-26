"use client";

import { RefreshCwIcon, TargetIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import type { GoalState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { getGoalContinuationDisplay } from "./goal-status-helpers";
import { Tooltip } from "./tooltip";

export function GoalStatus({
  className,
  goal,
}: {
  className?: string;
  goal: GoalState;
}) {
  const { t } = useI18n();
  const continuation = getGoalContinuationDisplay(goal);
  return (
    <div
      className={cn(
        "bg-background/90 border-border flex min-h-10 w-full items-center gap-3 rounded-t-xl border border-b-0 px-4 py-2 text-sm shadow-sm backdrop-blur-sm",
        className,
      )}
    >
      <TargetIcon className="text-primary size-4 shrink-0" />
      <div className="min-w-0 flex-1 truncate">
        <span className="text-muted-foreground mr-2">
          {t.inputBox.goalLabel}
        </span>
        <span className="font-medium">{goal.objective}</span>
      </div>
      {continuation && (
        <Tooltip
          content={t.inputBox.goalContinuationTooltip
            .replace("{count}", String(continuation.count))
            .replace("{max}", String(continuation.max))}
        >
          <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs tabular-nums">
            <RefreshCwIcon className="size-3" />
            {t.inputBox.goalContinuing
              .replace("{count}", String(continuation.count))
              .replace("{max}", String(continuation.max))}
          </span>
        </Tooltip>
      )}
    </div>
  );
}
