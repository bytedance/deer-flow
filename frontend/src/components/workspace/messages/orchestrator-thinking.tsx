import type { AIMessage } from "@langchain/langgraph-sdk";
import { ChevronUp, ListTodoIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { cn } from "@/lib/utils";

import { MarkdownContent } from "./markdown-content";
import { extractReasoningContentFromMessage } from "./message-steps";

export function OrchestratorThinking({
  message,
  isLoading,
}: {
  message: AIMessage;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);

  const reasoning = useMemo(
    () => extractReasoningContentFromMessage(message),
    [message],
  );

  const taskCount = useMemo(() => {
    let count = 0;
    for (const toolCall of message.tool_calls ?? []) {
      if (toolCall.name === "task") {
        count++;
      }
    }
    return count;
  }, [message]);

  if (!reasoning && taskCount === 0) {
    return null;
  }

  return (
    <ChainOfThought
      className="w-full gap-2 rounded-lg border py-0"
      open={!collapsed}
    >
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
                label={t.subtasks.taskAnalysis}
              />
              <ChevronUp
                className={cn(
                  "text-muted-foreground size-4",
                  !collapsed ? "" : "rotate-180",
                )}
              />
            </div>
          </Button>
        </div>
        <ChainOfThoughtContent className="px-4 pb-4">
          {reasoning && (
            <ChainOfThoughtStep
              label={
                <MarkdownContent
                  content={reasoning}
                  isLoading={isLoading}
                  rehypePlugins={rehypePlugins}
                />
              }
            />
          )}
          {taskCount > 0 && (
            <ChainOfThoughtStep
              label={t.subtasks.decomposedInto(taskCount)}
              icon={<ListTodoIcon className="size-4" />}
            />
          )}
        </ChainOfThoughtContent>
      </div>
    </ChainOfThought>
  );
}
