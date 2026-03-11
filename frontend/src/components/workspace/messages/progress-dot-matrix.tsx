import { memo } from "react";

import { cn } from "@/lib/utils";

const COLS = 14;
const ROWS = 3;
const TOTAL_DOTS = COLS * ROWS;

export interface ProgressDotMatrixProps {
  className?: string;
  /** Current step / message index */
  current: number;
  /** Total steps / messages */
  total: number;
  /** Task status */
  status: "in_progress" | "completed" | "failed";
}

export const ProgressDotMatrix = memo(function ProgressDotMatrix({
  className,
  current,
  total,
  status,
}: ProgressDotMatrixProps) {
  const filledDots =
    status === "completed"
      ? TOTAL_DOTS
      : status === "failed"
        ? Math.min(
            Math.round(total > 0 ? (current / total) * TOTAL_DOTS : 0),
            TOTAL_DOTS,
          )
        : Math.min(
            Math.round(total > 0 ? (current / total) * TOTAL_DOTS : 0),
            TOTAL_DOTS,
          );

  return (
    <div
      className={cn("shrink-0", className)}
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${COLS}, 3px)`,
        gridTemplateRows: `repeat(${ROWS}, 3px)`,
        gap: "2px",
        width: `${COLS * 3 + (COLS - 1) * 2}px`,
      }}
    >
      {Array.from({ length: TOTAL_DOTS }).map((_, i) => {
        const isFilled = i < filledDots;
        const isLeading = status === "in_progress" && i === filledDots;

        return (
          <div
            key={i}
            className={cn(
              "rounded-[1px] transition-colors duration-300",
              isFilled
                ? status === "failed"
                  ? "bg-red-400"
                  : "bg-emerald-400"
                : isLeading && status === "in_progress"
                  ? "animate-pulse bg-emerald-400/60"
                  : "bg-white/[0.08]",
            )}
            style={{ width: 3, height: 3 }}
          />
        );
      })}
    </div>
  );
});
