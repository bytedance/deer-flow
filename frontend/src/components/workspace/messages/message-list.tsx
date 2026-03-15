"use client";

import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { useCallback, useMemo, useRef } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractTextFromMessage,
  groupMessages,
  hasContent,
  hasPresentFiles,
  hasReasoning,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { StreamingIndicator } from "../streaming-indicator";

import { MarkdownContent } from "./markdown-content";
import { MessageGroup } from "./message-group";
import { MessageListItem } from "./message-list-item";
import { MessageListSkeleton } from "./skeleton";
import { SubtaskCard } from "./subtask-card";

export function MessageList({
  className,
  threadId,
  thread,
  paddingBottom = 160,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const messages = thread.messages;

  const groupedItems = useMemo(
    () => groupMessages(messages, (group) => group),
    [messages],
  );

  const renderGroup = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (index: number, group: any) => {
      if (group.type === "human" || group.type === "assistant") {
        return (
          <div className="flex flex-col gap-8">
            {group.messages.map(
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              (msg: any) => (
                <MessageListItem
                  key={`${group.id}/${msg.id}`}
                  message={msg}
                  isLoading={thread.isLoading}
                />
              ),
            )}
          </div>
        );
      } else if (group.type === "assistant:clarification") {
        const message = group.messages[0];
        if (message && hasContent(message)) {
          return (
            <MarkdownContent
              content={extractContentFromMessage(message)}
              isLoading={thread.isLoading}
              rehypePlugins={rehypePlugins}
            />
          );
        }
        return null;
      } else if (group.type === "assistant:present-files") {
        const files: string[] = [];
        for (const message of group.messages) {
          if (hasPresentFiles(message)) {
            const presentFiles = extractPresentFilesFromMessage(message);
            files.push(...presentFiles);
          }
        }
        return (
          <div className="w-full">
            {group.messages[0] && hasContent(group.messages[0]) && (
              <MarkdownContent
                content={extractContentFromMessage(group.messages[0])}
                isLoading={thread.isLoading}
                rehypePlugins={rehypePlugins}
                className="mb-4"
              />
            )}
            <ArtifactFileList files={files} threadId={threadId} />
          </div>
        );
      } else if (group.type === "assistant:subagent") {
        const tasks = new Set<Subtask>();
        for (const message of group.messages) {
          if (message.type === "ai") {
            for (const toolCall of message.tool_calls ?? []) {
              if (toolCall.name === "task") {
                const task: Subtask = {
                  id: toolCall.id!,
                  subagent_type: toolCall.args.subagent_type,
                  description: toolCall.args.description,
                  prompt: toolCall.args.prompt,
                  status: "in_progress",
                };
                updateSubtask(task);
                tasks.add(task);
              }
            }
          } else if (message.type === "tool") {
            const taskId = message.tool_call_id;
            if (taskId) {
              const result = extractTextFromMessage(message);
              if (result.startsWith("Task Succeeded. Result:")) {
                updateSubtask({
                  id: taskId,
                  status: "completed",
                  result: result.split("Task Succeeded. Result:")[1]?.trim(),
                });
              } else if (result.startsWith("Task failed.")) {
                updateSubtask({
                  id: taskId,
                  status: "failed",
                  error: result.split("Task failed.")[1]?.trim(),
                });
              } else if (result.startsWith("Task timed out")) {
                updateSubtask({
                  id: taskId,
                  status: "failed",
                  error: result,
                });
              } else {
                updateSubtask({
                  id: taskId,
                  status: "in_progress",
                });
              }
            }
          }
        }
        const results: React.ReactNode[] = [];
        for (const message of group.messages.filter(
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (message: any) => message.type === "ai",
        )) {
          if (hasReasoning(message)) {
            results.push(
              <MessageGroup
                key={"thinking-group-" + message.id}
                messages={[message]}
                isLoading={thread.isLoading}
              />,
            );
          }
          results.push(
            <div
              key="subtask-count"
              className="text-muted-foreground font-norma pt-2 text-sm"
            >
              {t.subtasks.executing(tasks.size)}
            </div>,
          );
          const taskIds = message.tool_calls?.map(
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (toolCall: any) => toolCall.id,
          );
          for (const taskId of taskIds ?? []) {
            results.push(
              <SubtaskCard
                key={"task-group-" + taskId}
                taskId={taskId}
                isLoading={thread.isLoading}
              />,
            );
          }
        }
        return (
          <div className="relative z-1 flex flex-col gap-2">{results}</div>
        );
      }
      return (
        <MessageGroup messages={group.messages} isLoading={thread.isLoading} />
      );
    },
    [t, thread.isLoading, rehypePlugins, threadId, updateSubtask],
  );

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }

  const totalCount = groupedItems.length + (thread.isLoading ? 1 : 0) + 1;

  return (
    <Conversation
      className={cn("flex size-full flex-col justify-center", className)}
    >
      <ConversationContent className="mx-auto w-full max-w-(--container-width-md) pt-12">
        <Virtuoso
          ref={virtuosoRef}
          useWindowScroll
          totalCount={totalCount}
          overscan={400}
          followOutput="smooth"
          itemContent={(index) => {
            if (index < groupedItems.length) {
              return (
                <div className="pb-8">
                  {renderGroup(index, groupedItems[index])}
                </div>
              );
            }
            if (thread.isLoading && index === groupedItems.length) {
              return <StreamingIndicator className="my-4" />;
            }
            return <div style={{ height: `${paddingBottom}px` }} />;
          }}
        />
      </ConversationContent>
    </Conversation>
  );
}
