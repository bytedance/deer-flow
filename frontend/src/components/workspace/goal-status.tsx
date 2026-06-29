import { TargetIcon } from "lucide-react";

import type { GoalState } from "@/core/threads";
import { cn } from "@/lib/utils";

export function GoalStatus({
  className,
  goal,
}: {
  className?: string;
  goal: GoalState;
}) {
  return (
    <div
      className={cn(
        "bg-background/90 border-border flex min-h-10 w-full items-center gap-3 rounded-t-xl border border-b-0 px-4 py-2 text-sm shadow-sm backdrop-blur-sm",
        className,
      )}
    >
      <TargetIcon className="text-primary size-4 shrink-0" />
      <div className="min-w-0 flex-1 truncate">
        <span className="text-muted-foreground mr-2">Goal</span>
        <span className="font-medium">{goal.objective}</span>
      </div>
      <div className="text-muted-foreground shrink-0 text-xs tabular-nums">
        {goal.continuation_count}/{goal.max_continuations}
      </div>
    </div>
  );
}
