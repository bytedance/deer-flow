import {
  CheckCircleIcon,
  ChevronRightIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { memo, useRef } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { Subtask } from "@/core/tasks/types";
import { cn } from "@/lib/utils";

export interface AgentDockProps {
  className?: string;
  tasks: Subtask[];
  selectedTaskId: string | null;
  onSelect: (taskId: string) => void;
}

export const AgentDock = memo(function AgentDock({
  className,
  tasks,
  selectedTaskId,
  onSelect,
}: AgentDockProps) {
  const { t } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollRight = () => {
    scrollRef.current?.scrollBy({ left: 200, behavior: "smooth" });
  };

  return (
    <div
      className={cn(
        "relative flex items-center border-t border-white/8 bg-[#161717]",
        className,
      )}
    >
      <div
        ref={scrollRef}
        className="scrollbar-none flex flex-1 items-center gap-1 overflow-x-auto px-3 py-2.5"
      >
        {tasks.map((task) => {
          const isSelected = task.id === selectedTaskId;
          const agentNumber = String((task.agentIndex ?? 0) + 1).padStart(
            2,
            "0",
          );

          const initials = (() => {
            const name = task.agentName || "Agent";
            const parts = name.split(/\s+/);
            if (parts.length >= 2) {
              return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
            }
            return name.substring(0, 2).toUpperCase();
          })();

          const statusLabel =
            task.status === "completed"
              ? t.subtasks.done
              : task.status === "failed"
                ? t.subtasks.error
                : t.subtasks.running;

          const statusIcon =
            task.status === "completed" ? (
              <CheckCircleIcon className="size-3 text-emerald-500" />
            ) : task.status === "failed" ? (
              <XCircleIcon className="size-3 text-red-500" />
            ) : (
              <Loader2Icon className="size-3 animate-spin text-white/40" />
            );

          return (
            <button
              key={task.id}
              type="button"
              className={cn(
                "flex shrink-0 cursor-pointer flex-col items-center gap-1 rounded-xl px-3 py-2 transition-all",
                isSelected
                  ? "bg-white/8 ring-1 ring-white/15"
                  : "hover:bg-white/[0.04]",
              )}
              onClick={() => onSelect(task.id)}
            >
              <div className="flex items-center gap-2">
                {/* Avatar circle */}
                <div
                  className={cn(
                    "flex size-8 items-center justify-center rounded-full border text-[10px] font-bold",
                    isSelected
                      ? "border-white/20 bg-white/10 text-white/80"
                      : "border-white/10 bg-white/5 text-white/50",
                  )}
                >
                  {initials}
                </div>
                {/* Number */}
                <span className="font-pixel text-xs text-white/40">
                  {agentNumber}
                </span>
              </div>
              {/* Status */}
              <span className="flex items-center gap-1 text-[10px] text-white/40">
                {statusIcon}
                {statusLabel}
              </span>
            </button>
          );
        })}
      </div>

      {/* Scroll hint arrow */}
      {tasks.length > 5 && (
        <button
          type="button"
          className="flex h-full shrink-0 items-center px-2 text-white/30 transition-colors hover:text-white/60"
          onClick={scrollRight}
        >
          <ChevronRightIcon className="size-4" />
        </button>
      )}
    </div>
  );
});
