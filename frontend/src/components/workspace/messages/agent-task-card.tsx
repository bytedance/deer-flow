import {
  CheckCircleIcon,
  CornerDownRightIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { memo, useMemo } from "react";

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { useI18n } from "@/core/i18n/hooks";
import type { Subtask } from "@/core/tasks/types";
import { cn } from "@/lib/utils";

import { ProgressDotMatrix } from "./progress-dot-matrix";

export interface AgentTaskCardProps {
  className?: string;
  task: Subtask;
  onClick?: () => void;
}

export const AgentTaskCard = memo(function AgentTaskCard({
  className,
  task,
  onClick,
}: AgentTaskCardProps) {
  const { t } = useI18n();

  const statusIcon = useMemo(() => {
    if (task.status === "completed") {
      return <CheckCircleIcon className="size-3.5 shrink-0 text-green-500" />;
    } else if (task.status === "failed") {
      return <XCircleIcon className="size-3.5 shrink-0 text-red-500" />;
    } else {
      return (
        <Loader2Icon className="text-muted-foreground size-3.5 shrink-0 animate-spin" />
      );
    }
  }, [task.status]);

  const agentNumber = String((task.agentIndex ?? 0) + 1).padStart(2, "0");

  const initials = useMemo(() => {
    const name = task.agentName || "Agent";
    const parts = name.split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
  }, [task.agentName]);

  return (
    <HoverCard openDelay={300} closeDelay={100}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          className={cn(
            "bg-muted/60 hover:bg-muted group flex w-full cursor-pointer items-start gap-3 rounded-xl px-3.5 py-3 text-left transition-colors",
            className,
          )}
          onClick={onClick}
        >
          {/* Avatar */}
          <div className="relative mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5 text-[10px] font-bold text-white/70">
            {initials}
          </div>

          {/* Content */}
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-normal text-white/55">
                {task.agentName || "Agent"}
              </span>
              <span className="font-pixel text-sm text-white/85">
                {agentNumber}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <CornerDownRightIcon className="size-3.5 shrink-0 text-white/25" />
              <span className="min-w-0 flex-1 truncate text-sm text-white/55">
                {task.description}
              </span>
              {/* Progress dots right-aligned */}
              <ProgressDotMatrix
                className="shrink-0"
                current={task.messageIndex}
                total={task.totalMessages}
                status={task.status}
              />
            </div>
          </div>
        </button>
      </HoverCardTrigger>
      <HoverCardContent
        className="w-72"
        side="top"
        align="start"
        sideOffset={8}
      >
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-full border border-white/10 bg-white/5 text-[10px] font-bold text-white/70">
              {initials}
            </div>
            <div>
              <div className="text-sm font-medium">{task.agentName}</div>
              <div className="text-muted-foreground text-xs">
                {task.subagent_type}
              </div>
            </div>
          </div>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {task.description}
          </p>
          <div className="text-muted-foreground flex items-center gap-1 text-[10px]">
            {statusIcon}
            <span>{t.subtasks[task.status]}</span>
          </div>
        </div>
      </HoverCardContent>
    </HoverCard>
  );
});
