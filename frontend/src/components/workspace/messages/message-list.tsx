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
import { agentNameFromType } from "@/core/tasks/utils";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { StreamingIndicator } from "../streaming-indicator";

import { AgentSwarmBlock } from "./agent-swarm-block";
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
  isNewThread = false,
  thread,
  messages: messagesProp,
  messagesOverride,
  paddingBottom = 160,
  isRegenerating,
  isUploadingFiles,
  pendingFileNames,
  isTransitioning,
  onEditMessage,
  onRegenerateMessage,
}: {
  className?: string;
  threadId: string;
  isNewThread?: boolean;
  thread: UseStream<AgentThreadState>;
  /** Explicit messages to display (from Chat.tsx filtering logic). */
  messages?: Message[];
  /** Legacy: When set (e.g. from onFinish), use instead of thread.messages so SSE end shows complete state. */
  messagesOverride?: Message[];
  paddingBottom?: number;
  isRegenerating?: boolean;
  isUploadingFiles?: boolean;
  pendingFileNames?: string[];
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

  // Persisted subagent trajectory data from the backend thread state.
  // Keyed by task_id, contains full trajectory messages for each completed subagent.
  const subagentTrajectories = (
    thread.values as Record<string, unknown> | undefined
  )?.subagent_trajectories as
    | Record<
        string,
        {
          task_id: string;
          messages?: unknown[];
        }
      >
    | undefined;

  // Sync subagent task state from messages into context (via useEffect, not render).
  // This avoids the React rule violation of updating state during render.
  const subagentTaskUpdates = useMemo(() => {
    const updates: (Partial<Subtask> & { id: string })[] = [];
    // We need to walk through all messages to find subagent groups.
    // Use the same grouping logic to identify tool calls and results.
    let agentCounter = 0;
    for (const message of stableMessages) {
      if (message.type === "ai") {
        for (const toolCall of message.tool_calls ?? []) {
          if (toolCall.name === "task" && toolCall.id) {
            // Check for persisted trajectory data from backend state
            const trajectory = subagentTrajectories?.[toolCall.id];
            const trajectoryMessages = Array.isArray(trajectory?.messages)
              ? (trajectory.messages as Message[])
              : [];
            updates.push({
              id: toolCall.id,
              subagent_type: toolCall.args?.subagent_type ?? "agent",
              description: toolCall.args?.description ?? "",
              prompt: toolCall.args?.prompt ?? "",
              status: "in_progress",
              agentName: agentNameFromType(toolCall.args?.subagent_type ?? "agent"),
              agentIndex: agentCounter++,
              messageIndex: 0,
              totalMessages: trajectoryMessages.length,
              messageHistory: trajectoryMessages,
              createdAt: Date.now(),
            });
          }
        }
      } else if (message.type === "tool" && message.tool_call_id) {
        const text = extractTextFromMessage(message);
        if (text.startsWith("Task Succeeded. Result:")) {
          updates.push({
            id: message.tool_call_id,
            status: "completed",
            result: text.split("Task Succeeded. Result:")[1]?.trim(),
          });
        } else if (text.startsWith("Task failed.")) {
          updates.push({
            id: message.tool_call_id,
            status: "failed",
            error: text.split("Task failed.")[1]?.trim(),
          });
        } else if (text.startsWith("Task timed out")) {
          updates.push({
            id: message.tool_call_id,
            status: "failed",
            error: text,
          });
        }
      }
    }
    return updates;
  }, [stableMessages, subagentTrajectories]);

  useEffect(() => {
    for (const update of subagentTaskUpdates) {
      updateSubtask(update);
    }
  }, [subagentTaskUpdates, updateSubtask]);

  // Find the last human message ID for attaching pending file badges
  // Must be before early return to satisfy rules of hooks
  const lastHumanMessageId = useMemo(() => {
    if (!pendingFileNames || pendingFileNames.length === 0) return null;
    for (let i = stableMessages.length - 1; i >= 0; i--) {
      if (stableMessages[i]?.type === "human") {
        return stableMessages[i]?.id ?? null;
      }
    }
    return null;
  }, [stableMessages, pendingFileNames]);

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
      const isLastHuman = group.type === "human" && group.messages[0]?.id === lastHumanMessageId;
      return (
        <MessageListItem
          key={group.id}
          message={group.messages[0]!}
          isLoading={thread.isLoading}
          isRegenerating={isRegenerating}
          pendingFileNames={isLastHuman ? pendingFileNames : undefined}
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
      // Task state is synced via useEffect above — here we only collect IDs and render.
      const results: React.ReactNode[] = [];
      const allTaskIds: string[] = [];
      let taskCount = 0;
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
        const taskIds = message.tool_calls
          ?.filter((tc) => tc.name === "task")
          ?.map((toolCall) => toolCall.id)
          .filter(Boolean) as string[];
        if (taskIds) {
          allTaskIds.push(...taskIds);
          taskCount += taskIds.length;
        }
      }

      // Use AgentSwarmBlock for 2+ tasks, SubtaskCard for single task
      if (allTaskIds.length >= 2) {
        results.push(
          <AgentSwarmBlock
            key={"swarm-" + group.id}
            taskIds={allTaskIds}
          />,
        );
      } else {
        results.push(
          <div
            key="subtask-count"
            className="text-muted-foreground font-norma pt-2 text-sm"
          >
            {t.subtasks.executing(taskCount)}
          </div>,
        );
        for (const taskId of allTaskIds) {
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
          pendingFileNames={message.id === lastHumanMessageId ? pendingFileNames : undefined}
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
        {!thread.isLoading &&
          !isTransitioning &&
          messages.length === 0 &&
          !isNewThread && (
          <ConversationEmptyState />
        )}
        {(thread.isLoading || isTransitioning || isUploadingFiles) && (
          <div className="my-4 flex items-center gap-3 transition-opacity duration-200">
            <StreamingIndicator
              showUsage={!isUploadingFiles}
              isLoading={thread.isLoading}
              usageEstimate={streamingUsageEstimate}
              statusOverride={isUploadingFiles ? "Processing files..." : undefined}
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
