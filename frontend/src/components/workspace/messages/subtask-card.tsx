import {
  CheckCircleIcon,
  ChevronUp,
  ClipboardListIcon,
  Loader2Icon,
  SparklesIcon,
  WrenchIcon,
  XCircleIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Button } from "@/components/ui/button";
import { ShineBorder } from "@/components/ui/shine-border";
import { useI18n } from "@/core/i18n/hooks";
import { hasToolCalls } from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import {
  streamdownPluginsWithoutRawHtml,
  streamdownWordAnimation,
} from "@/core/streamdown";
import {
  SafeStreamdown,
  toStreamdownComponents,
} from "@/core/streamdown/components";
import { fetchSubtaskSteps } from "@/core/tasks/api";
import { useSubtask, useUpdateSubtask } from "@/core/tasks/context";
import {
  formatSubtaskTokenUsage,
  resolveSubtaskModelLabel,
} from "@/core/tasks/presentation";
import { stepsForDisplay } from "@/core/tasks/steps";
import { explainLastToolCall } from "@/core/tools/utils";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";
import { FlipDisplay } from "../flip-display";

import { MarkdownContent } from "./markdown-content";

export function SubtaskCard({
  className,
  taskId,
  threadId,
  runId,
  isLoading,
}: {
  className?: string;
  taskId: string;
  threadId?: string;
  runId?: string;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(true);
  const task = useSubtask(taskId)!;
  const { models, tokenUsageEnabled } = useModels();
  const updateSubtask = useUpdateSubtask();
  const modelLabel = resolveSubtaskModelLabel(task.modelName, models);
  const tokenLabel = tokenUsageEnabled
    ? formatSubtaskTokenUsage(task.usage)
    : undefined;
  const runtimeUsageLabel = tokenUsageEnabled
    ? tokenLabel
      ? `${tokenLabel} ${t.tokenUsage.label}`
      : task.status === "in_progress"
        ? t.tokenUsage.collecting
        : t.tokenUsage.unavailableShort
    : undefined;

  // The card shows the subagent's step timeline (#3779): its reasoning turns
  // (AI text) interleaved with the tools it ran (by name). See stepsForDisplay
  // for what is kept/dropped.
  const displaySteps = stepsForDisplay(task.steps, task.status);

  // Backfill step history on expand for historical runs (#3779). Live runs
  // already have steps from SSE, so the `steps.length` guard skips the fetch.
  const stepsCount = task.steps?.length ?? 0;
  const backfilledRef = useRef(false);
  useEffect(() => {
    if (collapsed || backfilledRef.current || stepsCount > 0) {
      return;
    }
    if (!threadId || !runId) {
      return;
    }
    backfilledRef.current = true;
    fetchSubtaskSteps(threadId, runId, taskId)
      .then((steps) => {
        if (steps.length > 0) {
          updateSubtask({ id: taskId, steps });
        }
      })
      .catch(() => {
        // Allow a retry on the next expand if the fetch failed.
        backfilledRef.current = false;
      });
  }, [collapsed, stepsCount, threadId, runId, taskId, updateSubtask]);
  const icon = useMemo(() => {
    if (task.status === "completed") {
      return <CheckCircleIcon className="size-3" />;
    } else if (task.status === "failed") {
      return <XCircleIcon className="size-3 text-red-500" />;
    } else if (task.status === "in_progress") {
      return <Loader2Icon className="size-3 animate-spin" />;
    }
  }, [task.status]);
  return (
    <ChainOfThought
      className={cn("relative w-full gap-2 rounded-lg border py-0", className)}
      open={!collapsed}
    >
      <div
        className={cn(
          "ambilight z-[-1]",
          task.status === "in_progress" ? "enabled" : "",
        )}
      ></div>
      {task.status === "in_progress" && (
        <>
          <ShineBorder
            borderWidth={1.5}
            shineColor={["#A07CFE", "#FE8FB5", "#FFBE7B"]}
          />
        </>
      )}
      <div className="bg-background/95 flex w-full flex-col rounded-lg">
        <div className="flex w-full items-center justify-between p-0.5">
          <Button
            className="w-full items-start justify-start text-left"
            variant="ghost"
            onClick={() => setCollapsed(!collapsed)}
          >
            <div className="flex w-full items-center justify-between">
              <ChainOfThoughtStep
                className="font-normal"
                label={
                  task.status === "in_progress" ? (
                    <Shimmer duration={3} spread={3}>
                      {task.description}
                    </Shimmer>
                  ) : (
                    task.description
                  )
                }
                icon={<ClipboardListIcon />}
              ></ChainOfThoughtStep>
              <div className="flex items-center gap-1">
                {collapsed && (
                  <div
                    className={cn(
                      "text-muted-foreground flex items-center gap-1 text-xs font-normal",
                      task.status === "failed" ? "text-red-500 opacity-67" : "",
                    )}
                  >
                    {modelLabel && (
                      <span className="max-w-32 truncate" title={modelLabel}>
                        {modelLabel}
                      </span>
                    )}
                    {runtimeUsageLabel && (
                      <span
                        className="max-w-28 truncate"
                        title={runtimeUsageLabel}
                      >
                        {runtimeUsageLabel}
                      </span>
                    )}
                    {icon}
                    <FlipDisplay
                      className="max-w-[420px] truncate pb-1"
                      uniqueKey={task.latestMessage?.id ?? ""}
                    >
                      {task.status === "in_progress" &&
                      task.latestMessage &&
                      hasToolCalls(task.latestMessage)
                        ? explainLastToolCall(task.latestMessage, t)
                        : t.subtasks[task.status]}
                    </FlipDisplay>
                  </div>
                )}
                <ChevronUp
                  className={cn(
                    "text-muted-foreground size-4",
                    !collapsed ? "" : "rotate-180",
                  )}
                />
              </div>
            </div>
          </Button>
        </div>
        <ChainOfThoughtContent className="px-4 pb-4">
          {task.prompt && (
            <ChainOfThoughtStep
              label={
                <SafeStreamdown
                  {...streamdownPluginsWithoutRawHtml}
                  animated={streamdownWordAnimation}
                  components={toStreamdownComponents({ a: CitationLink })}
                  isAnimating={isLoading}
                >
                  {task.prompt}
                </SafeStreamdown>
              }
            ></ChainOfThoughtStep>
          )}
          {displaySteps.map((step, i) => {
            const isLastWhileRunning =
              task.status === "in_progress" && i === displaySteps.length - 1;
            const icon = isLastWhileRunning ? (
              <Loader2Icon className="size-4 animate-spin" />
            ) : step.kind === "tool" ? (
              <WrenchIcon className="size-4" />
            ) : (
              <SparklesIcon className="size-4" />
            );
            return (
              <ChainOfThoughtStep
                key={`${step.message_index}-${i}`}
                label={
                  step.kind === "tool" ? (
                    (step.tool_name ?? t.subtasks[task.status])
                  ) : (
                    <div className="text-muted-foreground line-clamp-3 text-sm">
                      <MarkdownContent content={step.text} isLoading={false} />
                    </div>
                  )
                }
                icon={icon}
              />
            );
          })}
          {task.status === "completed" && (
            <>
              <ChainOfThoughtStep
                label={t.subtasks.completed}
                icon={<CheckCircleIcon className="size-4" />}
              ></ChainOfThoughtStep>
              <ChainOfThoughtStep
                label={
                  task.result ? (
                    <MarkdownContent content={task.result} isLoading={false} />
                  ) : null
                }
              ></ChainOfThoughtStep>
            </>
          )}
          {task.status === "failed" && (
            <ChainOfThoughtStep
              label={<div className="text-red-500">{task.error}</div>}
              icon={<XCircleIcon className="size-4 text-red-500" />}
            ></ChainOfThoughtStep>
          )}
        </ChainOfThoughtContent>
      </div>
    </ChainOfThought>
  );
}
