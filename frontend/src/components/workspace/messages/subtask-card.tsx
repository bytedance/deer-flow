import {
  CheckCircleIcon,
  ChevronUp,
  ClipboardListIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Streamdown } from "streamdown";

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
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { streamdownPluginsWithWordAnimation } from "@/core/streamdown";
import type { Subtask } from "@/core/tasks";
import { useLatestSubtaskMessage } from "@/core/tasks/context";
import { explainLastToolCall } from "@/core/tools/utils";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";
import { FlipDisplay } from "../flip-display";

import { MarkdownContent } from "./markdown-content";

export function SubtaskCard({
  className,
  task,
  isLoading,
}: {
  className?: string;
  task: Subtask;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(true);
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const latestMessage = useLatestSubtaskMessage(task.id);
  const mergedTask = useMemo(
    () => (latestMessage ? { ...task, latestMessage } : task),
    [latestMessage, task],
  );
  const icon = useMemo(() => {
    if (mergedTask.status === "completed") {
      return <CheckCircleIcon className="size-3" />;
    } else if (mergedTask.status === "failed") {
      return <XCircleIcon className="size-3 text-red-500" />;
    } else if (mergedTask.status === "in_progress") {
      return <Loader2Icon className="size-3 animate-spin" />;
    }
  }, [mergedTask.status]);
  return (
    <ChainOfThought
      className={cn("relative w-full gap-2 rounded-lg border py-0", className)}
      open={!collapsed}
    >
      <div
        className={cn(
          "ambilight z-[-1]",
          mergedTask.status === "in_progress" ? "enabled" : "",
        )}
      ></div>
      {mergedTask.status === "in_progress" && (
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
                  mergedTask.status === "in_progress" ? (
                    <Shimmer duration={3} spread={3}>
                      {mergedTask.description}
                    </Shimmer>
                  ) : (
                    mergedTask.description
                  )
                }
                icon={<ClipboardListIcon />}
              ></ChainOfThoughtStep>
              <div className="flex items-center gap-1">
                {collapsed && (
                  <div
                    className={cn(
                      "text-muted-foreground flex items-center gap-1 text-xs font-normal",
                      mergedTask.status === "failed"
                        ? "text-red-500 opacity-67"
                        : "",
                    )}
                  >
                    {icon}
                    <FlipDisplay
                      className="max-w-[420px] truncate pb-1"
                      uniqueKey={mergedTask.latestMessage?.id ?? ""}
                    >
                      {mergedTask.status === "in_progress" &&
                      mergedTask.latestMessage &&
                      hasToolCalls(mergedTask.latestMessage)
                        ? explainLastToolCall(mergedTask.latestMessage, t)
                        : t.subtasks[mergedTask.status]}
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
          {mergedTask.prompt && (
            <ChainOfThoughtStep
              label={
                <Streamdown
                  {...streamdownPluginsWithWordAnimation}
                  components={{ a: CitationLink }}
                >
                  {mergedTask.prompt}
                </Streamdown>
              }
            ></ChainOfThoughtStep>
          )}
          {mergedTask.status === "in_progress" &&
            mergedTask.latestMessage &&
            hasToolCalls(mergedTask.latestMessage) && (
              <ChainOfThoughtStep
                label={t.subtasks.in_progress}
                icon={<Loader2Icon className="size-4 animate-spin" />}
              >
                {explainLastToolCall(mergedTask.latestMessage, t)}
              </ChainOfThoughtStep>
            )}
          {mergedTask.status === "completed" && (
            <>
              <ChainOfThoughtStep
                label={t.subtasks.completed}
                icon={<CheckCircleIcon className="size-4" />}
              ></ChainOfThoughtStep>
              <ChainOfThoughtStep
                label={
                  mergedTask.result ? (
                    <MarkdownContent
                      content={mergedTask.result}
                      isLoading={false}
                      rehypePlugins={rehypePlugins}
                    />
                  ) : null
                }
              ></ChainOfThoughtStep>
            </>
          )}
          {mergedTask.status === "failed" && (
            <ChainOfThoughtStep
              label={<div className="text-red-500">{mergedTask.error}</div>}
              icon={<XCircleIcon className="size-4 text-red-500" />}
            ></ChainOfThoughtStep>
          )}
        </ChainOfThoughtContent>
      </div>
    </ChainOfThought>
  );
}
