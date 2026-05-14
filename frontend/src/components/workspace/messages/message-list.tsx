import type { Message } from "@langchain/langgraph-sdk";
import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { ChevronUpIcon, Loader2Icon } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import { GenUIBlockList } from "@/components/genui";
import { Button } from "@/components/ui/button";
import { submitInteraction } from "@/core/genui";
import { extractBlockIdsFromMessages } from "@/core/genui/history";
import { recoverBlocksFromMessages } from "@/core/genui/sse-recovery";
import { useBlockStore } from "@/core/genui/store";
import {
  buildStreamingBlockExclusions,
  partitionStandaloneBlockIds,
} from "@/core/genui/visibility";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildTokenDebugSteps,
  type TokenUsageInlineMode,
} from "@/core/messages/usage-model";
import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractReasoningContentFromMessage,
  extractTextFromMessage,
  getAssistantTurnUsageMessages,
  getMessageGroups,
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
import { CopyButton } from "../copy-button";
import { StreamingIndicator } from "../streaming-indicator";

import { MarkdownContent } from "./markdown-content";
import { MessageGroup } from "./message-group";
import { MessageListItem } from "./message-list-item";
import {
  MessageTokenUsageDebugList,
  MessageTokenUsageList,
} from "./message-token-usage";
import { RetrievalSources } from "./retrieval-sources";
import { MessageListSkeleton } from "./skeleton";
import { SubtaskCard } from "./subtask-card";

export const MESSAGE_LIST_DEFAULT_PADDING_BOTTOM = 160;
export const MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM = 80;

const LOAD_MORE_HISTORY_THROTTLE_MS = 1200;

function getMessageKey(message: Message): string {
  return (
    message.id ??
    ("tool_call_id" in message ? message.tool_call_id : undefined) ??
    `${message.type}:${extractTextFromMessage(message)}`
  );
}

function areAllMessagesHistorical(
  messages: Message[],
  liveMessageKeys: Set<string>,
): boolean {
  return messages.every((message) => !liveMessageKeys.has(getMessageKey(message)));
}

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
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
  tokenUsageInlineMode?: TokenUsageInlineMode;
  hasMoreHistory?: boolean;
  loadMoreHistory?: () => void;
  isHistoryLoading?: boolean;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const messages = thread.messages;
  const blocks = useBlockStore((state) => state.blocks);
  const storeBlockIds = useMemo(() => Array.from(blocks.keys()), [blocks]);
  const groupedMessages = getMessageGroups(messages);
  const turnUsageMessagesByGroupIndex =
    getAssistantTurnUsageMessages(groupedMessages);
  const tokenDebugSteps = useMemo(
    () => buildTokenDebugSteps(messages, t),
    [messages, t],
  );

  const claimedBlockIds = useMemo(() => {
    const ids: string[] = [];
    for (const group of groupedMessages) {
      if (group.type === "assistant:processing") {
        ids.push(...extractBlockIdsFromMessages(group.messages));
      }
    }
    return ids;
  }, [groupedMessages]);

  const preStreamMessageKeysRef = useRef<Set<string>>(new Set());
  const preStreamBlockIdsRef = useRef<Set<string>>(new Set());
  const [liveStreamMessageKeys, setLiveStreamMessageKeys] = useState<
    Set<string>
  >(() => new Set());
  const wasLoadingRef = useRef(false);
  const effectiveLiveStreamMessageKeys = useMemo(() => {
    if (thread.isLoading) {
      return new Set(
        messages
          .map(getMessageKey)
          .filter((key) => !preStreamMessageKeysRef.current.has(key)),
      );
    }

    if (!thread.isLoading && wasLoadingRef.current) {
      return new Set(
        messages
          .map(getMessageKey)
          .filter((key) => !preStreamMessageKeysRef.current.has(key)),
      );
    }
    return liveStreamMessageKeys;
  }, [thread.isLoading, liveStreamMessageKeys, messages]);

  useEffect(() => {
    if (thread.isLoading && !wasLoadingRef.current) {
      preStreamMessageKeysRef.current = new Set(messages.map(getMessageKey));
      preStreamBlockIdsRef.current = new Set(storeBlockIds);
      setLiveStreamMessageKeys(new Set());
    }

    if (!thread.isLoading && wasLoadingRef.current) {
      setLiveStreamMessageKeys(
        new Set(
          messages
            .map(getMessageKey)
            .filter((key) => !preStreamMessageKeysRef.current.has(key)),
        ),
      );
    }

    wasLoadingRef.current = thread.isLoading;
  }, [thread.isLoading, messages, storeBlockIds]);

  const [historicalAnchoredBlockIds, setHistoricalAnchoredBlockIds] = useState<Set<string>>(
    () => new Set(),
  );
  const historicalMessages = useMemo(
    () =>
      messages.filter(
        (message) => !effectiveLiveStreamMessageKeys.has(getMessageKey(message)),
      ),
    [effectiveLiveStreamMessageKeys, messages],
  );
  const liveMessages = useMemo(
    () =>
      messages.filter((message) =>
        effectiveLiveStreamMessageKeys.has(getMessageKey(message)),
      ),
    [effectiveLiveStreamMessageKeys, messages],
  );

  useEffect(() => {
    if (messages.length === 0) return;

    recoverBlocksFromMessages(
      messages as { type?: string; content?: unknown }[],
    );

    const historicalBlockIds = extractBlockIdsFromMessages(historicalMessages);
    if (historicalBlockIds.length === 0) return;

    setHistoricalAnchoredBlockIds((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of historicalBlockIds) {
        if (!next.has(id)) {
          next.add(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [historicalMessages, messages]);

  const interactions = useBlockStore((state) => state.interactions);
  const historicalMessageBlockIds = useMemo(
    () =>
      Array.from(
        new Set([
          ...historicalAnchoredBlockIds,
          ...extractBlockIdsFromMessages(historicalMessages),
        ]),
      ),
    [historicalAnchoredBlockIds, historicalMessages],
  );
  const liveMessageBlockIds = useMemo(
    () => extractBlockIdsFromMessages(liveMessages),
    [liveMessages],
  );

  const { historicalBlockIds: historicalStandaloneBlockIds, tailBlockIds: unclaimedBlockIds } =
    useMemo(() => {
      return partitionStandaloneBlockIds({
        claimedBlockIds,
        storeBlockIds,
        historicalMessageBlockIds,
        liveMessageBlockIds,
        preStreamBlockIds: Array.from(preStreamBlockIdsRef.current),
        blocks,
        interactions,
      });
    }, [
      claimedBlockIds,
      storeBlockIds,
      historicalMessageBlockIds,
      liveMessageBlockIds,
      blocks,
      interactions,
    ]);

  const firstLiveGroupIndex = useMemo(
    () =>
      groupedMessages.findIndex((group) =>
        group.messages.some((message) =>
          effectiveLiveStreamMessageKeys.has(getMessageKey(message)),
        ),
      ),
    [effectiveLiveStreamMessageKeys, groupedMessages],
  );
  const currentTurnStartIndex = useMemo(() => {
    if (firstLiveGroupIndex >= 0) {
      for (let index = firstLiveGroupIndex - 1; index >= 0; index -= 1) {
        if (groupedMessages[index]?.type === "human") {
          return index;
        }
      }
      return firstLiveGroupIndex;
    }

    if (thread.isLoading) {
      for (let index = groupedMessages.length - 1; index >= 0; index -= 1) {
        if (groupedMessages[index]?.type === "human") {
          return index;
        }
      }
    }

    return -1;
  }, [firstLiveGroupIndex, groupedMessages, thread.isLoading]);

  const renderAssistantCopyButton = useCallback((messages: Message[]) => {
    const clipboardData = [...messages]
      .reverse()
      .filter((message) => message.type === "ai")
      .map((message) => {
        const content = extractContentFromMessage(message);
        return content ?? extractReasoningContentFromMessage(message) ?? "";
      })
      .find((content) => content.length > 0);

    if (!clipboardData) {
      return null;
    }

    return (
      <div className="mt-2 flex justify-start opacity-0 transition-opacity delay-200 duration-300 group-hover/assistant-turn:opacity-100">
        <CopyButton clipboardData={clipboardData} />
      </div>
    );
  }, []);

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

  const handleInteraction = useCallback(
    (callbackId: string, payload: Record<string, unknown>) => {
      void submitInteraction(threadId, callbackId, payload);
    },
    [threadId],
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
          let renderedGroup: React.ReactNode = null;

          if (group.type === "human" || group.type === "assistant") {
            renderedGroup = (
              <div
                key={`${group.type}-${group.id}`}
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
                {group.type === "assistant" && (
                  <RetrievalSources messages={messages} />
                )}
                {group.type === "assistant" &&
                  renderAssistantCopyButton(group.messages)}
              </div>
            );
          } else if (group.type === "assistant:clarification") {
            const message = group.messages[0];
            if (message && hasContent(message)) {
              renderedGroup = (
                <div key={`clarification-${group.id}`} className="w-full">
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
          } else if (group.type === "assistant:present-files") {
            const files: string[] = [];
            for (const message of group.messages) {
              if (hasPresentFiles(message)) {
                const presentFiles = extractPresentFilesFromMessage(message);
                files.push(...presentFiles);
              }
            }
            return (
              <div className="w-full" key={`present-files-${group.id}`}>
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
                  const result = extractTextFromMessage(message);
                  if (result.startsWith("Task Succeeded. Result:")) {
                    updateSubtask({
                      id: taskId,
                      status: "completed",
                      result: result
                        .split("Task Succeeded. Result:")[1]
                        ?.trim(),
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
            renderedGroup = (
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
          } else if (group.type === "assistant:processing") {
            const blockIds = extractBlockIdsFromMessages(group.messages);
            return (
              <div key={`processing-${group.id}`} className="w-full">
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
                {blockIds.length > 0 && (
                  <GenUIBlockList
                    threadId={threadId}
                    blockIds={blockIds}
                    disableExpiration={
                      !thread.isLoading &&
                      areAllMessagesHistorical(
                        group.messages,
                        effectiveLiveStreamMessageKeys,
                      )
                    }
                    onInteraction={handleInteraction}
                  />
                )}
                {renderTokenUsage({
                  messages: group.messages,
                  turnUsageMessages,
                  inlineDebug: false,
                })}
              </div>
            );
          }

          if (!renderedGroup) {
            return null;
          }

          if (
            groupIndex === currentTurnStartIndex &&
            historicalStandaloneBlockIds.length > 0
          ) {
            return (
              <Fragment key={`group-${group.id ?? groupIndex}`}>
                <GenUIBlockList
                  threadId={threadId}
                  blockIds={historicalStandaloneBlockIds}
                  disableExpiration={true}
                  onInteraction={handleInteraction}
                />
                {renderedGroup}
              </Fragment>
            );
          }

          return renderedGroup;
        })}
        {currentTurnStartIndex < 0 && historicalStandaloneBlockIds.length > 0 && (
          <GenUIBlockList
            threadId={threadId}
            blockIds={historicalStandaloneBlockIds}
            disableExpiration={true}
            onInteraction={handleInteraction}
          />
        )}
        {!thread.isLoading && unclaimedBlockIds.length > 0 && (
          <GenUIBlockList
            threadId={threadId}
            blockIds={unclaimedBlockIds}
            disableExpiration={true}
            onInteraction={handleInteraction}
          />
        )}
        {thread.isLoading && <StreamingIndicator className="my-4" />}
        {thread.isLoading && (
          <GenUIBlockList
            threadId={threadId}
            excludeBlockIds={buildStreamingBlockExclusions(
              claimedBlockIds,
              historicalStandaloneBlockIds,
            )}
            onInteraction={handleInteraction}
          />
        )}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
