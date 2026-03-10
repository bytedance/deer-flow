import {
  CheckCircleIcon,
  ClockIcon,
  Loader2Icon,
  MonitorIcon,
  XCircleIcon,
  XIcon,
} from "lucide-react";
import { memo, useEffect, useMemo, useRef } from "react";

import { ChainOfThoughtStep } from "@/components/ai-elements/chain-of-thought";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/core/i18n/hooks";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks/types";
import { cn } from "@/lib/utils";

import { MarkdownContent } from "./markdown-content";
import { AgentDock } from "./agent-dock";
import { convertToSteps, ToolCall as WorkspaceToolCall } from "./message-group";

// --- AgentDetailPanel ---

export interface AgentDetailPanelProps {
  className?: string;
  task: Subtask;
  allTasks: Subtask[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string) => void;
  onClose: () => void;
}

export const AgentDetailPanel = memo(function AgentDetailPanel({
  className,
  task,
  allTasks,
  selectedTaskId,
  onSelectTask,
  onClose,
}: AgentDetailPanelProps) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevHistoryLenRef = useRef(0);
  const resultCacheRef = useRef(new Map<string, unknown>());

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const len = task.messageHistory?.length ?? 0;
    if (len > prevHistoryLenRef.current && scrollRef.current) {
      const el = scrollRef.current.querySelector(
        "[data-radix-scroll-area-viewport]",
      );
      if (el) {
        requestAnimationFrame(() => {
          el.scrollTop = el.scrollHeight;
        });
      }
    }
    prevHistoryLenRef.current = len;
  }, [task.messageHistory?.length]);

  // Convert message history into chain-of-thought steps
  // (reasoning + tool calls paired with their results)
  const steps = useMemo(
    () => convertToSteps(task.messageHistory ?? [], resultCacheRef.current),
    [task.messageHistory],
  );

  const completedCount = allTasks.filter(
    (t) => t.status === "completed",
  ).length;
  const totalCount = allTasks.length;
  const agentNumber = String((task.agentIndex ?? 0) + 1).padStart(2, "0");

  const statusBadge = useMemo(() => {
    if (task.status === "completed") {
      return (
        <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 text-emerald-400">
          <CheckCircleIcon className="size-3.5" />
          <span className="text-xs font-medium">{t.subtasks.completed}</span>
        </div>
      );
    } else if (task.status === "failed") {
      return (
        <div className="flex items-center gap-1.5 rounded-full bg-red-500/10 px-3 py-1 text-red-400">
          <XCircleIcon className="size-3.5" />
          <span className="text-xs font-medium">{t.subtasks.failed}</span>
        </div>
      );
    }
    return (
      <div className="flex items-center gap-1.5 rounded-full bg-white/5 px-3 py-1 text-white/50">
        <Loader2Icon className="size-3.5 animate-spin" />
        <span className="text-xs font-medium">{t.subtasks.running}</span>
      </div>
    );
  }, [task.status, t]);

  return (
    <div
      className={cn(
        "flex h-full flex-col overflow-hidden rounded-2xl border border-white/8 bg-[#161717]",
        className,
      )}
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between px-5 py-3.5">
        <div className="flex items-center gap-3">
          <MonitorIcon className="size-5 text-white/50" />
          <span className="font-pixel text-lg text-white/85">
            {t.subtasks.agentConsole}
          </span>
          <div className="flex items-center gap-1.5">
            <div
              className={cn(
                "size-2 rounded-full",
                completedCount === totalCount
                  ? "bg-emerald-500"
                  : "animate-pulse bg-emerald-500/70",
              )}
            />
            <span className="text-sm text-white/50">
              {t.subtasks.taskProgress(completedCount, totalCount)}
            </span>
          </div>
        </div>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={onClose}
          className="text-white/40 hover:text-white/70"
        >
          <XIcon className="size-4" />
        </Button>
      </div>

      {/* Sub-header: Agent label + status */}
      <div className="flex shrink-0 items-center justify-between border-t border-white/8 px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-full border border-white/12 bg-white/5 font-pixel text-xs text-white/60">
            {agentNumber}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-white/85">
              {task.agentName || "Agent"}
            </div>
            <div className="max-w-full truncate text-xs text-white/40">
              {task.description}
            </div>
          </div>
        </div>
        {statusBadge}
      </div>

      {/* Content: Chain-of-thought steps */}
      <ScrollArea ref={scrollRef} className="min-h-0 flex-1 border-t border-white/8 [&_[data-slot=scroll-area-viewport]]:!overflow-x-hidden [&_[data-slot=scroll-area-viewport]>div]:!block [&_[data-slot=scroll-area-viewport]>div]:!min-w-0">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-5 [overflow-wrap:anywhere]">
          {/* Task prompt */}
          {task.prompt && (
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wider text-white/35">
                {t.subtasks.taskPrompt}
              </div>
              <p className="text-sm leading-relaxed text-white/80">
                {task.prompt}
              </p>
            </div>
          )}

          {/* Agent Timeline */}
          {steps.length > 0 && (
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wider text-white/35">
                {t.subtasks.agentTimeline}
              </div>
              {steps.map((step, idx) => {
                if (step.type === "reasoning") {
                  return (
                    <ChainOfThoughtStep
                      key={step.id ?? `r-${idx}`}
                      icon={ClockIcon}
                      className="text-[rgb(175,174,163)]"
                      label={step.title ?? t.common.thinking}
                      showConnector={idx < steps.length - 1}
                    >
                      {step.body && (
                        <MarkdownContent
                          content={step.body}
                          isLoading={false}
                          rehypePlugins={rehypePlugins}
                          className="max-w-full overflow-hidden break-words text-sm leading-relaxed [&_p]:leading-[1.7]"
                        />
                      )}
                    </ChainOfThoughtStep>
                  );
                }
                return (
                  <WorkspaceToolCall
                    key={step.id ?? `tc-${idx}`}
                    id={step.id}
                    messageId={step.messageId}
                    name={step.name}
                    args={step.args}
                    result={step.result}
                    isLoading={false}
                  />
                );
              })}
            </div>
          )}

          {/* Result */}
          {task.status === "completed" && task.result && (
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wider text-emerald-400">
                {t.subtasks.result}
              </div>
              <MarkdownContent
                content={task.result}
                isLoading={false}
                rehypePlugins={rehypePlugins}
                className="max-w-full overflow-hidden break-words text-sm leading-relaxed [&_p]:leading-[1.7]"
              />
            </div>
          )}
          {task.status === "failed" && task.error && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wider text-red-400">
                {t.subtasks.error}
              </div>
              <p className="text-sm leading-relaxed text-red-300">{task.error}</p>
            </div>
          )}

          {/* Loading indicator for in-progress */}
          {task.status === "in_progress" && (
            <div className="flex items-center gap-2.5 py-3 text-white/50">
              <Loader2Icon className="size-4 animate-spin" />
              <span className="text-sm">{t.subtasks.running}</span>
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Footer: Agent dock carousel */}
      <AgentDock
        tasks={allTasks}
        selectedTaskId={selectedTaskId}
        onSelect={onSelectTask}
      />
    </div>
  );
});
