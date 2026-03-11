import { WorkflowIcon } from "lucide-react";
import { memo, useMemo } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/core/i18n/hooks";
import { useSelectedSubtask, useSubtaskContext } from "@/core/tasks/context";
import type { Subtask } from "@/core/tasks/types";
import { cn } from "@/lib/utils";

import { AgentTaskCard } from "./agent-task-card";

export interface AgentSwarmBlockProps {
  className?: string;
  taskIds: string[];
}

export const AgentSwarmBlock = memo(function AgentSwarmBlock({
  className,
  taskIds,
}: AgentSwarmBlockProps) {
  const { t } = useI18n();
  const { tasks } = useSubtaskContext();
  const { setSelectedTaskId } = useSelectedSubtask();

  const sortedTasks = useMemo(() => {
    return taskIds
      .map((id) => tasks[id])
      .filter((t): t is Subtask => t !== undefined)
      .sort((a, b) => (a.agentIndex ?? 0) - (b.agentIndex ?? 0));
  }, [taskIds, tasks]);

  const completedCount = sortedTasks.filter(
    (task) => task.status === "completed",
  ).length;
  const totalCount = sortedTasks.length;

  return (
    <div
      className={cn(
        "fade-in-0 slide-in-from-bottom-3 animate-in w-full rounded-xl border border-white/8 duration-300",
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3.5 py-3">
        <WorkflowIcon className="text-muted-foreground size-4" />
        <span className="text-foreground text-sm font-medium">
          {t.subtasks.agentSwarm}
        </span>
        <span className="text-muted-foreground text-xs">
          | {t.subtasks.taskProgress(completedCount, totalCount)}
        </span>
      </div>

      {/* Task cards */}
      <ScrollArea className="max-h-[600px]">
        <div className="flex flex-col gap-2 px-2.5 pb-3">
          {sortedTasks.map((task) => (
            <AgentTaskCard
              key={task.id}
              task={task}
              onClick={() => setSelectedTaskId(task.id)}
            />
          ))}
        </div>
      </ScrollArea>
    </div>
  );
});
