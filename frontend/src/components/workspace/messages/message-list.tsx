import type { Message } from "@langchain/langgraph-sdk";
import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { ChevronUpIcon, Loader2Icon, Share2Icon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildTokenDebugSteps,
  type TokenUsageInlineMode,
} from "@/core/messages/usage-model";
import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractTextFromMessage,
  getAssistantTurnCopyData,
  getAssistantTurnUsageMessages,
  getMessageGroups,
  getStreamingMessageLookup,
  hasContent,
  hasPresentFiles,
  hasReasoning,
  isAssistantMessageGroupStreaming,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import { parseSubtaskResult } from "@/core/tasks/subtask-result";
import type { AgentThreadState } from "@/core/threads";
import { createThreadShare } from "@/core/threads/api";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { CopyButton } from "../copy-button";
import { StreamingIndicator } from "../streaming-indicator";
import { Tooltip } from "../tooltip";

import { MarkdownContent } from "./markdown-content";
import { MessageGroup } from "./message-group";
import { MessageListItem } from "./message-list-item";
import {
  MessageTokenUsageDebugList,
  MessageTokenUsageList,
} from "./message-token-usage";
import { MessageListSkeleton } from "./skeleton";
import { SubtaskCard } from "./subtask-card";

export const MESSAGE_LIST_DEFAULT_PADDING_BOTTOM = 24;

const LOAD_MORE_HISTORY_THROTTLE_MS = 1200;

function LoadMoreHistoryIndicator({
  isLoading,
  hasMore,
  loadMore,
}: {
  isLoading?: boolean;
  hasMore?: boolean;
  loadMore?: () => void;
}) {
  const { t } = useI18n();
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastLoadRef = useRef(0);

  const throttledLoadMore = useCallback(() => {
    if (!hasMore || isLoading) {
      return;
    }

    const now = Date.now();
    const remaining =
      LOAD_MORE_HISTORY_THROTTLE_MS - (now - lastLoadRef.current);

    if (remaining <= 0) {
      lastLoadRef.current = now;
      loadMore?.();
      return;
    }

    if (timeoutRef.current) {
      return;
    }

    timeoutRef.current = setTimeout(() => {
      timeoutRef.current = null;
      if (!hasMore || isLoading) {
        return;
      }
      lastLoadRef.current = Date.now();
      loadMore?.();
    }, remaining);
  }, [hasMore, isLoading, loadMore]);

  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasMore) {
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          throttledLoadMore();
        }
      },
      {
        rootMargin: "120px 0px 0px 0px",
      },
    );

    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, [hasMore, throttledLoadMore]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  if (!hasMore && !isLoading) {
    return null;
  }

  return (
    <div ref={sentinelRef} className="flex w-full justify-center">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-muted-foreground hover:text-foreground rounded-full px-3"
        disabled={(isLoading ?? false) || !hasMore}
        onClick={throttledLoadMore}
      >
        {isLoading ? (
          <>
            <Loader2Icon className="mr-2 size-4 animate-spin" />
            {t.common.loading}
          </>
        ) : (
          <>
            <ChevronUpIcon className="mr-2 size-4" />
            {t.common.loadMore}
          </>
        )}
      </Button>
    </div>
  );
}

export function MessageList({
  className,
  threadId,
  thread,
  paddingBottom = MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  tokenUsageInlineMode = "off",
  hasMoreHistory,
  loadMoreHistory,
  isHistoryLoading,
  enableSharing = true,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
  tokenUsageInlineMode?: TokenUsageInlineMode;
  hasMoreHistory?: boolean;
  loadMoreHistory?: () => void;
  isHistoryLoading?: boolean;
  enableSharing?: boolean;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const messages = thread.messages;
  const groupedMessages = useMemo(() => getMessageGroups(messages), [messages]);
  const turnUsageMessagesByGroupIndex =
    getAssistantTurnUsageMessages(groupedMessages);
  const previousHumanMessagesByGroupIndex = useMemo(() => {
    const previousByIndex: Message[][] = [];
    let previousHumanMessages: Message[] | null = null;

    groupedMessages.forEach((group, index) => {
      previousByIndex[index] = previousHumanMessages ?? [];
      if (group.type === "human") {
        previousHumanMessages = group.messages;
      } else if (group.type === "assistant") {
        previousHumanMessages = null;
      }
    });

    return previousByIndex;
  }, [groupedMessages]);
  const tokenDebugSteps = useMemo(
    () => buildTokenDebugSteps(messages, t),
    [messages, t],
  );
  const streamingMessages = useMemo(
    () =>
      getStreamingMessageLookup(
        messages,
        thread.isLoading,
        thread.getMessagesMetadata,
      ),
    [messages, thread.getMessagesMetadata, thread.isLoading],
  );

  const renderAssistantActions = useCallback(
    (
      messages: Message[],
      isStreaming: boolean,
      previousMessages: Message[],
    ) => {
      const clipboardData = getAssistantTurnCopyData(messages, { isStreaming });

      if (!clipboardData) {
        return null;
      }

      const shareMessageIds = [...previousMessages, ...messages]
        .map((message) => message.id)
        .filter((id): id is string => typeof id === "string" && id.length > 0);

      return (
        <div
          className={cn(
            "mt-2 flex justify-start gap-1 opacity-0 transition-opacity",
            "delay-200 duration-300 group-hover/assistant-turn:opacity-100",
          )}
        >
          <CopyButton clipboardData={clipboardData} />
          {enableSharing && (
            <Tooltip content={t.common.share}>
              <Button
                aria-label={t.common.share}
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={async () => {
                  if (shareMessageIds.length === 0) {
                    toast.error(t.conversation.noMessages);
                    return;
                  }
                  try {
                    const share = await createThreadShare({
                      threadId,
                      messageIds: shareMessageIds,
                      title: thread.values.title,
                    });
                    const shareUrl = new URL(
                      `/share/${share.share_id}`,
                      window.location.origin,
                    ).toString();
                    try {
                      await navigator.clipboard.writeText(shareUrl);
                    } catch {
                      toast.error(t.clipboard.failedToCopyToClipboard);
                      return;
                    }
                    toast.success(t.clipboard.linkCopied);
                  } catch (err) {
                    toast.error(
                      err instanceof Error
                        ? err.message
                        : "Failed to create share.",
                    );
                  }
                }}
              >
                <Share2Icon size={12} />
              </Button>
            </Tooltip>
          )}
        </div>
      );
    },
    [
      t.clipboard.failedToCopyToClipboard,
      t.clipboard.linkCopied,
      t.common.share,
      t.conversation.noMessages,
      enableSharing,
      thread.values.title,
      threadId,
    ],
  );

  const renderTokenUsage = useCallback(
    ({
      messages,
      turnUsageMessages,
      inlineDebug = true,
      debugMessageIds,
    }: {
      messages: Message[];
      turnUsageMessages?: Message[] | null;
      inlineDebug?: boolean;
      debugMessageIds?: string[];
    }) => {
      if (tokenUsageInlineMode === "per_turn") {
        return (
          <MessageTokenUsageList
            enabled={true}
            isLoading={thread.isLoading}
            messages={turnUsageMessages ?? []}
          />
        );
      }

      if (tokenUsageInlineMode === "step_debug" && inlineDebug) {
        const messageIds = new Set(
          debugMessageIds ??
            messages
              .filter((message) => message.type === "ai")
              .map((message) => message.id)
              .filter((id): id is string => typeof id === "string"),
        );
        return (
          <MessageTokenUsageDebugList
            enabled={true}
            isLoading={thread.isLoading}
            steps={tokenDebugSteps.filter((step) =>
              messageIds.has(step.messageId),
            )}
          />
        );
      }

      return null;
    },
    [thread.isLoading, tokenDebugSteps, tokenUsageInlineMode],
  );

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }

  return (
    <Conversation
      className={cn("flex size-full flex-col justify-center", className)}
    >
      <ConversationContent className="mx-auto w-full max-w-(--container-width-md) gap-8 pt-8">
        <LoadMoreHistoryIndicator
          isLoading={isHistoryLoading}
          hasMore={hasMoreHistory}
          loadMore={loadMoreHistory}
        />
        {groupedMessages.map((group, groupIndex) => {
          const turnUsageMessages = turnUsageMessagesByGroupIndex[groupIndex];
          const previousMessages =
            previousHumanMessagesByGroupIndex[groupIndex] ?? [];

          if (group.type === "human" || group.type === "assistant") {
            return (
              <div
                key={group.id}
                className={cn(
                  "w-full",
                  group.type === "assistant" && "group/assistant-turn",
                )}
              >
                {group.messages.map((msg) => {
                  return (
                    <MessageListItem
                      key={`${group.id}/${msg.id}`}
                      message={msg}
                      isLoading={thread.isLoading}
                      threadId={threadId}
                      showCopyButton={group.type !== "assistant"}
                    />
                  );
                })}
                {renderTokenUsage({
                  messages: group.messages,
                  turnUsageMessages,
                })}
                {group.type === "assistant" &&
                  renderAssistantActions(
                    group.messages,
                    isAssistantMessageGroupStreaming(
                      group.messages,
                      streamingMessages,
                    ),
                    previousMessages,
                  )}
              </div>
            );
          } else if (group.type === "assistant:clarification") {
            const message = group.messages[0];
            if (message && hasContent(message)) {
              return (
                <div key={group.id} className="w-full">
                  <MarkdownContent
                    content={extractContentFromMessage(message)}
                    isLoading={thread.isLoading}
                    rehypePlugins={rehypePlugins}
                  />
                  {renderTokenUsage({
                    messages: group.messages,
                    turnUsageMessages,
                  })}
                </div>
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
                    className="mb-4"
                  />
                )}
                <ArtifactFileList files={files} threadId={threadId} />
                {renderTokenUsage({
                  messages: group.messages,
                  turnUsageMessages,
                })}
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
                  const parsed = parseSubtaskResult(
                    extractTextFromMessage(message),
                  );
                  updateSubtask({ id: taskId, ...parsed });
                }
              }
            }

            const results: React.ReactNode[] = [];
            const subagentDebugMessageIds: string[] = [];
            if (tasks.size > 0) {
              results.push(
                <div
                  key="subtask-count"
                  className="text-muted-foreground pt-2 text-sm font-normal"
                >
                  {t.subtasks.executing(tasks.size)}
                </div>,
              );
            }
            for (const message of group.messages.filter(
              (message) => message.type === "ai",
            )) {
              if (hasReasoning(message)) {
                results.push(
                  <MessageGroup
                    key={"thinking-group-" + message.id}
                    messages={[message]}
                    isLoading={thread.isLoading}
                    tokenDebugSteps={tokenDebugSteps.filter(
                      (step) => step.messageId === message.id,
                    )}
                    showTokenDebugSummaries={
                      tokenUsageInlineMode === "step_debug"
                    }
                  />,
                );
              } else if (message.id) {
                subagentDebugMessageIds.push(message.id);
              }
              const taskIds = message.tool_calls
                ?.filter((toolCall) => toolCall.name === "task")
                .map((toolCall) => toolCall.id);
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
                {renderTokenUsage({
                  messages: group.messages,
                  turnUsageMessages,
                  debugMessageIds: subagentDebugMessageIds,
                })}
              </div>
            );
          }
          return (
            <div key={"group-" + group.id} className="w-full">
              <MessageGroup
                messages={group.messages}
                isLoading={thread.isLoading}
                tokenDebugSteps={tokenDebugSteps.filter((step) =>
                  group.messages.some(
                    (message) => message.id === step.messageId,
                  ),
                )}
                showTokenDebugSummaries={tokenUsageInlineMode === "step_debug"}
              />
              {renderTokenUsage({
                messages: group.messages,
                turnUsageMessages,
                inlineDebug: false,
              })}
            </div>
          );
        })}
        {thread.isLoading && <StreamingIndicator className="my-4" />}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
