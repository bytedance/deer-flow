"use client";

import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

type VisualizeProgressProps = {
  className?: string;
  hint?: string;
  loading: boolean;
  value: number;
};

export function VisualizeProgress({
  className,
  hint = "Preparing the slim VSFX runtime…",
  loading,
  value,
}: VisualizeProgressProps) {
  if (!loading) {
    return null;
  }

  const percent = Number.isFinite(value) ? Math.min(Math.max(value, 0), 100) : 0;

  return (
    <div
      aria-live="polite"
      className={cn(
        "bg-background/90 absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 rounded-md border p-6 text-center backdrop-blur-sm",
        className,
      )}
      data-testid="visualize-progress"
    >
      <div className="w-full max-w-xs space-y-2">
        <Progress value={percent} />
        <p className="text-sm font-medium">{Math.round(percent)}%</p>
      </div>
      <p className="text-muted-foreground text-sm">{hint}</p>
    </div>
  );
}
