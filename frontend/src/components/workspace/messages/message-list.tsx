import type { Message } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useEffect, useMemo, useRef } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
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
import {
  TurnUsageDisplay,
  estimateTokensFromText,
} from "./turn-usage-display";

export function MessageList({
  className,
  threadId,
  thread,
  messages: messagesProp,
  messagesOverride,
  paddingBottom = 160,
  isRegenerating,
  isTransitioning,
  onEditMessage,
  onRegenerateMessage,
}: {
  className?: string;
  threadId: string;
  thread: UseStream<AgentThreadState>;
  /** Explicit messages to display (from Chat.tsx filtering logic). */
  messages?: Message[];
  /** Legacy: When set (e.g. from onFinish), use instead of thread.messages so SSE end shows complete state. */
  messagesOverride?: Message[];
  paddingBottom?: number;
  isRegenerating?: boolean;
  isTransitioning?: boolean;
  onEditMessage?: (messageId: string, newContent: string) => void;
  onRegenerateMessage?: (messageId: string, content: string) => void;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const valuesMessages = Array.isArray(thread.values?.messages)
    ? (thread.values.messages as Message[])
    : [];
  const historyMessages = (() => {
    for (let index = thread.history.length - 1; index >= 0; index -= 1) {
      const state = thread.history[index];
      if (state && Array.isArray(state.values?.messages)) {
        return state.values.messages as Message[];
      }
    }
    return [] as Message[];
  })();
  const streamMessages = thread.messages ?? [];
  const messages =
    messagesProp ??
    messagesOverride ??
    (thread.isLoading
      ? streamMessages.length > 0
        ? streamMessages
        : valuesMessages.length > 0
          ? valuesMessages
          : historyMessages
      : valuesMessages.length > 0
        ? valuesMessages
        : historyMessages.length > 0
          ? historyMessages
          : streamMessages);
  const streamingUsageEstimate = useMemo(() => {
    if (!thread.isLoading || messages.length === 0) {
      return undefined;
    }

    const findLastMessage = (type: Message["type"]) => {
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (message?.type === type) {
          return message;
        }
      }
      return undefined;
    };

    const lastHuman = findLastMessage("human");
    const lastAi = findLastMessage("ai");

    if (!lastHuman && !lastAi) {
      return undefined;
    }

    return {
      inputTokens: lastHuman
        ? estimateTokensFromText(extractTextFromMessage(lastHuman))
        : 0,
      outputTokens: lastAi
        ? estimateTokensFromText(extractTextFromMessage(lastAi))
        : 0,
    };
  }, [messages, thread.isLoading]);
  const lastVisibleMessagesRef = useRef<Message[]>([]);
  const stableMessages = useMemo(() => {
    if (messages.length > 0) {
      return messages;
    }
    if (isTransitioning && lastVisibleMessagesRef.current.length > 0) {
      return lastVisibleMessagesRef.current;
    }
    return messages;
  }, [messages, isTransitioning]);

  useEffect(() => {
    if (messages.length > 0) {
      lastVisibleMessagesRef.current = messages;
    }
  }, [messages]);

  useEffect(() => {
    lastVisibleMessagesRef.current = [];
  }, [threadId]);

  if (thread.isThreadLoading) {
    return <MessageListSkeleton />;
  }

  type GroupLike = {
    type:
      | "human"
      | "assistant"
      | "assistant:clarification"
      | "assistant:present-files"
      | "assistant:subagent"
      | "assistant:processing";
    id: string | undefined;
    messages: Message[];
  };

  const mapGroupToNode = (group: GroupLike) => {
    if (group.type === "human" || group.type === "assistant") {
      return (
        <MessageListItem
          key={group.id}
          message={group.messages[0]!}
          isLoading={thread.isLoading}
          isRegenerating={isRegenerating}
          onEdit={onEditMessage}
          onRegenerate={onRegenerateMessage}
        />
      );
    } else if (group.type === "assistant:clarification") {
      const message = group.messages[0];
      if (message && hasContent(message)) {
        return (
          <MarkdownContent
            key={group.id}
            content={extractContentFromMessage(message)}
            isLoading={thread.isLoading}
            rehypePlugins={rehypePlugins}
            className="font-claude-response-body"
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
        <div className="w-full" key={group.id}>
          {group.messages[0] && hasContent(group.messages[0]) && (
            <MarkdownContent
              content={extractContentFromMessage(group.messages[0])}
              isLoading={thread.isLoading}
              rehypePlugins={rehypePlugins}
              className="font-claude-response-body mb-4"
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
        (message) => message.type === "ai",
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
        const taskIds = message.tool_calls?.map((toolCall) => toolCall.id);
        for (const taskId of taskIds ?? []) {
          results.push(
            <SubtaskCard
              key={"task-group-" + taskId}
              taskId={taskId!}
              isLoading={thread.isLoading}
            />,
          );
        }
      }
      return (
        <div
          key={"subtask-group-" + group.id}
          className="relative z-1 flex flex-col gap-2"
        >
          {results}
        </div>
      );
    }
    return (
      <MessageGroup
        key={"group-" + group.id}
        messages={group.messages}
        isLoading={thread.isLoading}
      />
    );
  };

  let messageNodes: React.ReactNode[] = [];
  try {
    messageNodes = groupMessages(stableMessages, mapGroupToNode);
  } catch (error) {
    console.error(
      "Failed to group thread messages, falling back to raw render.",
      error,
    );
    messageNodes = stableMessages
      .filter((message) => message.type === "human" || message.type === "ai")
      .map((message) => (
        <MessageListItem
          key={message.id}
          message={message}
          isLoading={thread.isLoading}
          isRegenerating={isRegenerating}
          onEdit={onEditMessage}
          onRegenerate={onRegenerateMessage}
        />
      ));
  }

  return (
    <Conversation
      className={cn("flex size-full flex-col justify-center", className)}
    >
      <ConversationContent
        className={cn(
          "mx-auto w-full max-w-(--container-width-md) gap-8 pt-12 transition-opacity duration-200",
          isTransitioning && messages.length === 0 && "opacity-90",
        )}
      >
        {messageNodes}
        {!thread.isLoading && !isTransitioning && messages.length === 0 && (
          <ConversationEmptyState />
        )}
        {(thread.isLoading || isTransitioning) && (
          <div className="my-4 flex items-center gap-3 transition-opacity duration-200">
            <StreamingIndicator
              showUsage
              isLoading={thread.isLoading}
              usageEstimate={streamingUsageEstimate}
            />
          </div>
        )}
        {!thread.isLoading && !isTransitioning && (
          <TurnUsageDisplay isLoading={false} />
        )}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
