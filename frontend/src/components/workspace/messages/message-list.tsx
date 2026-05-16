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
import {
  fetchResolvedBlockHistory,
  extractResolvedBlockIdsFromMessages,
  getHistoryMessageKey,
} from "@/core/genui/history";
import { useBlockStore, type UIBlock } from "@/core/genui/store";
import { partitionStandaloneBlockIds, isSubmittedBlock, filterSupersededInteractiveBlockIds } from "@/core/genui/visibility";
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
  isTransientMessageName,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { CopyButton } from "../copy-button";
import { StreamingIndicator } from "../streaming-indicator";

import { GenerationProcessPanel } from "./generation-process-panel";
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
const DUPLICATE_MARKDOWN_MIN_LENGTH = 20;

const LOAD_MORE_HISTORY_THROTTLE_MS = 1200;

const getMessageKey = getHistoryMessageKey;

function getGroupRenderKey(
  group: ReturnType<typeof getMessageGroups>[number],
  index: number,
): string {
  return `${group.type}-${group.id ?? index}`;
}

function areAllMessagesHistorical(
  messages: Message[],
  liveMessageKeys: Set<string>,
): boolean {
  return messages.every((message) => !liveMessageKeys.has(getMessageKey(message)));
}

function normalizeComparableMarkdown(content: string): string {
  return content.replace(/\r\n/g, "\n").trim().replace(/\n{3,}/g, "\n\n");
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
  // LangGraph streaming sometimes yields the same final AI message twice
  // (different chunk updates not merged by the SDK). Dedup by message id so
  // downstream grouping/extraction sees each message exactly once.
  const messages = useMemo(() => {
    const seen = new Set<string>();
    const result: Message[] = [];
    for (const m of thread.messages) {
      if (m.id) {
        if (seen.has(m.id)) continue;
        seen.add(m.id);
      }
      result.push(m);
    }
    return result;
  }, [thread.messages]);
  const messagesStableKey = useMemo(
    () => `${messages.length}:${messages[messages.length - 1]?.id ?? "none"}`,
    [messages.length, messages[messages.length - 1]?.id],
  );
  const blocks = useBlockStore((state) => state.blocks);
  const [resolvedBlockHistory, setResolvedBlockHistory] = useState<
    Awaited<ReturnType<typeof fetchResolvedBlockHistory>>
  >({
    blocks: [],
    blockIdsByMessageKey: new Map(),
    duplicatedRawBlockIds: new Set(),
  });

  useEffect(() => {
    fetchResolvedBlockHistory(threadId, messages).then((history) => {
      setResolvedBlockHistory(history);
      // Populate interaction state from backend data (survives page refresh).
      const store = useBlockStore.getState();
      for (const block of history.blocks) {
        if (block.interaction_status === "submitted" && block.block_id) {
          store.setInteractionSuccess(block.block_id);
        }
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, messagesStableKey]);
  const storeBlockIds = useMemo(
    () =>
      Array.from(blocks.keys()).filter(
        (blockId) => !resolvedBlockHistory.duplicatedRawBlockIds.has(blockId),
      ),
    [blocks, resolvedBlockHistory.duplicatedRawBlockIds],
  );
  const tokenDebugSteps = useMemo(
    () => buildTokenDebugSteps(messages, t),
    [messages, t],
  );

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
  const liveTurnHasVisibleOutput = useMemo(
    () =>
      liveMessages.some((message) => {
        if (isTransientMessageName(message.name)) {
          return false;
        }

        if (message.type === "ai") {
          return hasContent(message);
        }

        if (message.type !== "tool") {
          return false;
        }

        if (message.name === "present_files") {
          return true;
        }

        const text = extractTextFromMessage(message);
        return text.includes("<!--ui_block:") || text.includes("block_id=");
      }),
    [liveMessages],
  );
  const visibleMessages = useMemo(
    () =>
      messages.filter((message) => {
        if (!isTransientMessageName(message.name)) {
          return true;
        }

        return (
          thread.isLoading &&
          !liveTurnHasVisibleOutput &&
          effectiveLiveStreamMessageKeys.has(getMessageKey(message))
        );
      }),
    [
      effectiveLiveStreamMessageKeys,
      liveTurnHasVisibleOutput,
      messages,
      thread.isLoading,
    ],
  );
  const groupedMessages = useMemo(
    () => getMessageGroups(visibleMessages, thread.isLoading),
    [visibleMessages, thread.isLoading],
  );
  const turnUsageMessagesByGroupIndex =
    getAssistantTurnUsageMessages(groupedMessages);
  const claimedBlockIds = useMemo(() => {
    const ids: string[] = [];
    for (const group of groupedMessages) {
      if (group.type === "assistant:processing") {
        ids.push(
          ...extractResolvedBlockIdsFromMessages(
            group.messages,
            resolvedBlockHistory.blockIdsByMessageKey,
          ),
        );
      }
    }
    return ids;
  }, [groupedMessages, resolvedBlockHistory.blockIdsByMessageKey]);
  const blocksById = useMemo(() => {
    const next = new Map<string, UIBlock>();
    for (const block of resolvedBlockHistory.blocks) {
      next.set(block.block_id, block);
    }
    for (const block of blocks.values()) {
      next.set(block.block_id, block);
    }
    return next;
  }, [blocks, resolvedBlockHistory.blocks]);
  const interactions = useBlockStore((state) => state.interactions);
  const guidanceGroupIndices = useMemo(() => {
    const indices = new Set<number>();
    for (let i = 0; i < groupedMessages.length; i++) {
      const group = groupedMessages[i];
      if (group?.type !== "assistant") continue;

      // Look BACKWARD past any consecutive assistant groups to find the processing group
      let prevNonAssistant = i > 0 ? groupedMessages[i - 1] : undefined;
      let p = i - 1;
      while (prevNonAssistant?.type === "assistant" && p > 0) {
        p--;
        prevNonAssistant = groupedMessages[p];
      }
      if (prevNonAssistant?.type !== "assistant:processing") continue;
      const prevBlockIds = extractResolvedBlockIdsFromMessages(
        prevNonAssistant.messages,
        resolvedBlockHistory.blockIdsByMessageKey,
      );
      const interactiveFormBlocks = prevBlockIds
        .map((id) => blocksById.get(id))
        .filter(
          (block): block is UIBlock =>
            !!block && !!block.interactive && !block.functional_interaction,
        );
      if (interactiveFormBlocks.length === 0) continue;

      // Look FORWARD past any consecutive assistant groups to find the next non-assistant
      let nextNonAssistant = i + 1 < groupedMessages.length ? groupedMessages[i + 1] : undefined;
      let j = i + 1;
      while (nextNonAssistant?.type === "assistant" && j < groupedMessages.length) {
        j++;
        nextNonAssistant = groupedMessages[j];
      }
      // Hide guidance text when:
      //   (a) followed by a human message (visible chat reply), OR
      //   (b) the preceding interactive form has already been submitted —
      //       form submissions are hidden messages, so there is no human group
      //       to anchor against, but a stale "please submit" text after a
      //       submitted form is the same kind of noise we want to drop.
      const followedByHuman = nextNonAssistant?.type === "human";
      const formSubmitted = interactiveFormBlocks.some((block) =>
        isSubmittedBlock(block, interactions),
      );
      if (!followedByHuman && !formSubmitted) continue;

      indices.add(i);
    }
    return indices;
  }, [groupedMessages, resolvedBlockHistory.blockIdsByMessageKey, blocksById, interactions]);
  const comparableMarkdownBlockContents = useMemo(() => {
    const contents = new Set<string>();
    for (const block of blocksById.values()) {
      const content =
        block.component === "markdown" ? block.props.content : undefined;
      if (typeof content !== "string") {
        continue;
      }

      const normalized = normalizeComparableMarkdown(content);
      if (
        normalized.startsWith("# ") &&
        normalized.length >= DUPLICATE_MARKDOWN_MIN_LENGTH
      ) {
        contents.add(normalized);
      }
    }
    return contents;
  }, [blocksById]);

  useEffect(() => {
    if (messages.length === 0) return;

    const historicalBlockIds = extractResolvedBlockIdsFromMessages(
      historicalMessages,
      resolvedBlockHistory.blockIdsByMessageKey,
    );
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
  }, [
    historicalMessages,
    messages,
    resolvedBlockHistory.blockIdsByMessageKey,
  ]);

  const historicalMessageBlockIds = useMemo(
    () =>
      Array.from(
        new Set([
          ...historicalAnchoredBlockIds,
          ...extractResolvedBlockIdsFromMessages(
            historicalMessages,
            resolvedBlockHistory.blockIdsByMessageKey,
          ),
        ]),
      ),
    [
      historicalAnchoredBlockIds,
      historicalMessages,
      resolvedBlockHistory.blockIdsByMessageKey,
    ],
  );
  const liveMessageBlockIds = useMemo(
    () =>
      extractResolvedBlockIdsFromMessages(
        liveMessages,
        resolvedBlockHistory.blockIdsByMessageKey,
      ),
    [liveMessages, resolvedBlockHistory.blockIdsByMessageKey],
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
    if (firstLiveGroupIndex < 0) {
      return -1;
    }

    if (groupedMessages[firstLiveGroupIndex]?.type === "human") {
      return firstLiveGroupIndex;
    }

    for (let index = firstLiveGroupIndex - 1; index >= 0; index -= 1) {
      if (groupedMessages[index]?.type === "human") {
        return index;
      }
    }

    return firstLiveGroupIndex;
  }, [firstLiveGroupIndex, groupedMessages]);

  const claimedBlockAnchorById = useMemo(() => {
    const anchors = new Map<string, string>();

    for (const [groupIndex, group] of groupedMessages.entries()) {
      if (group.type !== "assistant:processing") {
        continue;
      }

      const groupKey = getGroupRenderKey(group, groupIndex);
      for (const blockId of extractResolvedBlockIdsFromMessages(
        group.messages,
        resolvedBlockHistory.blockIdsByMessageKey,
      )) {
        if (!anchors.has(blockId)) {
          anchors.set(blockId, groupKey);
        }
      }
    }

    return anchors;
  }, [groupedMessages, resolvedBlockHistory.blockIdsByMessageKey]);

  const desiredHistoricalAnchorAfterGroupKey = useMemo(() => {
    if (historicalStandaloneBlockIds.length === 0) {
      return undefined;
    }

    if (currentTurnStartIndex > 0) {
      const anchorGroup = groupedMessages[currentTurnStartIndex - 1];
      return anchorGroup
        ? getGroupRenderKey(anchorGroup, currentTurnStartIndex - 1)
        : null;
    }

    if (currentTurnStartIndex === 0 || groupedMessages.length === 0) {
      return null;
    }

    const lastGroupIndex = groupedMessages.length - 1;
    const lastGroup = groupedMessages[lastGroupIndex];
    return lastGroup ? getGroupRenderKey(lastGroup, lastGroupIndex) : null;
  }, [
    currentTurnStartIndex,
    groupedMessages,
    historicalStandaloneBlockIds.length,
  ]);

  const [
    blockAnchorById,
    setBlockAnchorById,
  ] = useState<Map<string, string | null>>(() => new Map());

  useEffect(() => {
    setBlockAnchorById(new Map());
  }, [threadId]);

  useEffect(() => {
    if (
      claimedBlockAnchorById.size === 0 &&
      historicalStandaloneBlockIds.length === 0
    ) {
      return;
    }

    setBlockAnchorById((prev) => {
      let changed = false;
      const next = new Map(prev);

      for (const [blockId, anchorGroupKey] of claimedBlockAnchorById) {
        if (next.has(blockId)) {
          continue;
        }
        next.set(blockId, anchorGroupKey);
        changed = true;
      }

      for (const blockId of historicalStandaloneBlockIds) {
        if (next.has(blockId)) {
          continue;
        }
        next.set(blockId, desiredHistoricalAnchorAfterGroupKey ?? null);
        changed = true;
      }

      if (!changed) {
        return prev;
      }

      return next;
    });
  }, [
    claimedBlockAnchorById,
    desiredHistoricalAnchorAfterGroupKey,
    historicalStandaloneBlockIds.length,
    historicalStandaloneBlockIds,
  ]);

  const groupedHistoricalStandaloneBlocks = useMemo(() => {
    const beforeMessageBlockIds: string[] = [];
    const fallbackBlockIds: string[] = [];
    const blockIdsByAnchorGroupKey = new Map<string, string[]>();
    const knownGroupKeys = new Set(
      groupedMessages.map((group, index) => getGroupRenderKey(group, index)),
    );

    for (const blockId of historicalStandaloneBlockIds) {
      const anchorAfterGroupKey =
        blockAnchorById.get(blockId) ??
        desiredHistoricalAnchorAfterGroupKey;

      if (anchorAfterGroupKey === null) {
        beforeMessageBlockIds.push(blockId);
        continue;
      }

      if (
        anchorAfterGroupKey !== undefined &&
        knownGroupKeys.has(anchorAfterGroupKey)
      ) {
        const anchoredBlockIds =
          blockIdsByAnchorGroupKey.get(anchorAfterGroupKey) ?? [];
        anchoredBlockIds.push(blockId);
        blockIdsByAnchorGroupKey.set(anchorAfterGroupKey, anchoredBlockIds);
        continue;
      }

      fallbackBlockIds.push(blockId);
    }

    return {
      beforeMessageBlockIds,
      blockIdsByAnchorGroupKey,
      fallbackBlockIds,
    };
  }, [
    blockAnchorById,
    desiredHistoricalAnchorAfterGroupKey,
    groupedMessages,
    historicalStandaloneBlockIds.length,
    historicalStandaloneBlockIds,
  ]);

  type MessageGroupType = (typeof groupedMessages)[number];

  type RenderItem =
    | { type: "group"; group: MessageGroupType; groupIndex: number }
    | {
        type: "merged-processing";
        groups: MessageGroupType[];
        startIndex: number;
        totalSteps: number;
        isLive: boolean;
        hasBlocks: boolean;
      };

  const renderItems = useMemo<RenderItem[]>(() => {
    const items: RenderItem[] = [];
    let i = 0;

    while (i < groupedMessages.length) {
      const group = groupedMessages[i];
      if (!group) {
        i++;
        continue;
      }

      if (group.type !== "assistant:processing") {
        items.push({ type: "group", group, groupIndex: i });
        i++;
        continue;
      }

      // Find consecutive processing groups
      let end = i;
      while (
        end + 1 < groupedMessages.length &&
        groupedMessages[end + 1]?.type === "assistant:processing"
      ) {
        end++;
      }

      const processingGroups = groupedMessages.slice(i, end + 1);
      const isLive = processingGroups.some((g) =>
        g.messages.some((msg) =>
          effectiveLiveStreamMessageKeys.has(getMessageKey(msg)),
        ),
      );

      // Count total steps and check if any group has GenUI blocks
      let totalSteps = 0;
      let hasBlocks = false;
      for (const pg of processingGroups) {
        for (const msg of pg.messages) {
          if (msg.type === "ai") {
            if (extractReasoningContentFromMessage(msg)) totalSteps++;
            for (const tc of msg.tool_calls ?? []) {
              if (tc.name !== "task") totalSteps++;
            }
          }
        }
        if (
          extractResolvedBlockIdsFromMessages(
            pg.messages,
            resolvedBlockHistory.blockIdsByMessageKey,
          ).length > 0
        ) {
          hasBlocks = true;
        }
      }

      items.push({
        type: "merged-processing",
        groups: processingGroups,
        startIndex: i,
        totalSteps,
        isLive,
        hasBlocks,
      });

      i = end + 1;
    }

    return items;
  }, [groupedMessages, effectiveLiveStreamMessageKeys, resolvedBlockHistory.blockIdsByMessageKey]);

  // Each block_id is "owned" by the first merged-processing item whose messages
  // reference it. Later merged items must skip blocks they don't own — otherwise
  // a block_id that leaks into a subsequent turn's messages (e.g. the model
  // re-invoking render_ui on the same callback, or a tool response echoing the
  // marker) gets rendered twice.
  const blockOwnerByItemIdx = useMemo(() => {
    const ownerByBlockId = new Map<string, number>();
    for (let idx = 0; idx < renderItems.length; idx++) {
      const item = renderItems[idx];
      if (item?.type !== "merged-processing") continue;
      for (const pg of item.groups) {
        const ids = extractResolvedBlockIdsFromMessages(
          pg.messages,
          resolvedBlockHistory.blockIdsByMessageKey,
        );
        for (const id of ids) {
          if (!ownerByBlockId.has(id)) {
            ownerByBlockId.set(id, idx);
          }
        }
      }
    }
    return ownerByBlockId;
  }, [renderItems, resolvedBlockHistory.blockIdsByMessageKey]);

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
    (
      callbackId: string,
      payload: Record<string, unknown>,
      blockId?: string,
    ) => {
      void submitInteraction(threadId, blockId, callbackId, payload);
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
        {groupedHistoricalStandaloneBlocks.beforeMessageBlockIds.length > 0 && (
            <GenUIBlockList
              threadId={threadId}
              blockIds={groupedHistoricalStandaloneBlocks.beforeMessageBlockIds}
              disableExpiration={true}
              onInteraction={handleInteraction}
            />
          )}
        {renderItems.map((item, itemIndex) => {
          if (item.type === "merged-processing") {
            const firstGroup = item.groups[0];
            const lastGroup = item.groups[item.groups.length - 1];
            if (!firstGroup || !lastGroup) return null;

            const panelKey = `merged-${item.startIndex}-${firstGroup.id ?? item.startIndex}`;

            // Collect blocks for all processing groups in the merge.
            // Only keep blocks owned by this merged item — block_ids that leak
            // into a later turn's messages are skipped here so they only render
            // once (in the item that first introduced them).
            const allBlockIds: string[] = [];
            for (const pg of item.groups) {
              for (const id of extractResolvedBlockIdsFromMessages(
                pg.messages,
                resolvedBlockHistory.blockIdsByMessageKey,
              )) {
                if (blockOwnerByItemIdx.get(id) === itemIndex) {
                  allBlockIds.push(id);
                }
              }
            }

            // Split into output blocks (always visible) and process blocks (collapsible).
            // Submitted interactive blocks are excluded — interaction status comes
            // from the backend via fetchResolvedBlockHistory.

            // Determine if the entire merged item is historical
            const allGroupsHistorical = item.groups.every((pg) =>
              areAllMessagesHistorical(
                pg.messages,
                effectiveLiveStreamMessageKeys,
              ),
            );

            const outputBlockIds: string[] = [];
            const rawProcessBlockIds: string[] = [];
            for (const id of allBlockIds) {
              const block = blocksById.get(id);
              if (!block) continue;
              if (isSubmittedBlock(block, interactions)) continue;
              if (!block.interactive || block.functional_interaction) {
                outputBlockIds.push(id);
              } else {
                rawProcessBlockIds.push(id);
              }
            }
            // Deduplicate by callback_id in case the backend model called
            // render_ui twice for the same interactive form in one turn.
            const processBlockIds = filterSupersededInteractiveBlockIds(
              rawProcessBlockIds,
              blocksById,
            );

            // Collect anchored blocks for all groups in the merge
            const anchoredBlockIds: string[] = [];
            for (let gi = item.startIndex; gi < item.startIndex + item.groups.length; gi++) {
              const g = groupedMessages[gi];
              if (!g) continue;
              const gk = getGroupRenderKey(g, gi);
              const anchored = groupedHistoricalStandaloneBlocks.blockIdsByAnchorGroupKey.get(gk);
              if (anchored) anchoredBlockIds.push(...anchored);
            }

            return (
              <Fragment key={panelKey}>
                {(processBlockIds.length > 0 || item.totalSteps > 0) && (
                  <GenerationProcessPanel
                    stepCount={item.totalSteps}
                    defaultExpanded={item.isLive || thread.isLoading || processBlockIds.length > 0}
                  >
                    <div className="flex flex-col gap-3">
                      {item.groups.map((pg, pgOffset) => {
                        const origIndex = item.startIndex + pgOffset;
                        const turnUsageMessages = turnUsageMessagesByGroupIndex[origIndex];

                        return (
                          <div key={`${origIndex}-processing-${pg.id}`} className="w-full">
                            <MessageGroup
                              messages={pg.messages}
                              isLoading={thread.isLoading}
                              tokenDebugSteps={tokenDebugSteps.filter((step) =>
                                pg.messages.some(
                                  (message) => message.id === step.messageId,
                                ),
                              )}
                              showTokenDebugSummaries={tokenUsageInlineMode === "step_debug"}
                            />
                            {renderTokenUsage({
                              messages: pg.messages,
                              turnUsageMessages,
                              inlineDebug: false,
                            })}
                          </div>
                        );
                      })}
                      {processBlockIds.length > 0 && (
                        <GenUIBlockList
                          threadId={threadId}
                          blockIds={processBlockIds}
                          disableExpiration={allGroupsHistorical}
                          onInteraction={handleInteraction}
                        />
                      )}
                    </div>
                  </GenerationProcessPanel>
                )}
                {outputBlockIds.length > 0 && (
                  <GenUIBlockList
                    threadId={threadId}
                    blockIds={outputBlockIds}
                    disableExpiration={allGroupsHistorical}
                    onInteraction={handleInteraction}
                  />
                )}
                {anchoredBlockIds.length > 0 && (
                  <GenUIBlockList
                    threadId={threadId}
                    blockIds={anchoredBlockIds}
                    disableExpiration={true}
                    onInteraction={handleInteraction}
                  />
                )}
              </Fragment>
            );
          }

          // Regular (non-merged) group rendering
          const group = item.group;
          const groupIndex = item.groupIndex;

          // Hide AI guidance text that sits between form creation and submission
          if (
            group.type === "assistant" &&
            guidanceGroupIndices.has(groupIndex)
          ) {
            return null;
          }

          const turnUsageMessages = turnUsageMessagesByGroupIndex[groupIndex];
          const previousItem = itemIndex > 0 ? renderItems[itemIndex - 1] : null;
          const previousGroup =
            previousItem?.type === "group"
              ? previousItem.group
              : previousItem?.type === "merged-processing"
                ? previousItem.groups[previousItem.groups.length - 1] ?? null
                : null;
          const assistantGroupContent =
            group.type === "assistant"
              ? normalizeComparableMarkdown(
                  group.messages
                    .map((message) => extractContentFromMessage(message))
                    .filter((content) => content.length > 0)
                    .join("\n\n"),
                )
              : "";
          const previousProcessingMarkdownMatches =
            previousGroup?.type === "assistant:processing" &&
            assistantGroupContent.startsWith("# ")
              ? extractResolvedBlockIdsFromMessages(
                  previousGroup.messages,
                  resolvedBlockHistory.blockIdsByMessageKey,
                ).some((blockId) => {
                  const block = blocksById.get(blockId);
                  const content =
                    block?.component === "markdown"
                      ? block.props.content
                      : undefined;
                  if (typeof content !== "string") return false;
                  const normalizedBlock = normalizeComparableMarkdown(content);
                  return (
                    assistantGroupContent.includes(normalizedBlock) ||
                    normalizedBlock.includes(assistantGroupContent)
                  );
                })
              : false;
          const shouldHideDuplicateAssistantMarkdown =
            group.type === "assistant" &&
            assistantGroupContent.startsWith("# ") &&
            assistantGroupContent.length >= DUPLICATE_MARKDOWN_MIN_LENGTH &&
            (previousProcessingMarkdownMatches ||
              comparableMarkdownBlockContents.has(assistantGroupContent) ||
              Array.from(comparableMarkdownBlockContents).some(
                (blockContent) =>
                  blockContent.length > DUPLICATE_MARKDOWN_MIN_LENGTH &&
                  (assistantGroupContent.includes(blockContent) ||
                    blockContent.includes(assistantGroupContent)),
              ));
          let renderedGroup: React.ReactNode = null;

          if (shouldHideDuplicateAssistantMarkdown) {
            return null;
          }

          if (group.type === "human" || group.type === "assistant") {
            renderedGroup = (
              <div
                key={`${group.type}-${groupIndex}-${group.id ?? groupIndex}`}
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
                <div key={`${groupIndex}-clarification-${group.id}`} className="w-full">
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
              <div className="w-full" key={`${groupIndex}-present-files-${group.id}`}>
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
                key={`${groupIndex}-subtask-group-${group.id}`}
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
            const blockIds = extractResolvedBlockIdsFromMessages(
              group.messages,
              resolvedBlockHistory.blockIdsByMessageKey,
            );
            renderedGroup = (
              <div key={`${groupIndex}-processing-${group.id}`} className="w-full">
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

          const groupKey = getGroupRenderKey(group, groupIndex);
          const anchoredBlockIds =
            groupedHistoricalStandaloneBlocks.blockIdsByAnchorGroupKey.get(
              groupKey,
            );

          if (anchoredBlockIds && anchoredBlockIds.length > 0) {
            return (
              <Fragment key={`${groupIndex}-group-${group.id ?? groupIndex}`}>
                {renderedGroup}
                <GenUIBlockList
                  threadId={threadId}
                  blockIds={anchoredBlockIds}
                  disableExpiration={true}
                  onInteraction={handleInteraction}
                />
              </Fragment>
            );
          }

          return renderedGroup;
        })}
        {groupedHistoricalStandaloneBlocks.fallbackBlockIds.length > 0 && (
          <GenUIBlockList
            threadId={threadId}
            blockIds={groupedHistoricalStandaloneBlocks.fallbackBlockIds}
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
        {thread.isLoading && unclaimedBlockIds.length > 0 && (
          <GenUIBlockList
            threadId={threadId}
            blockIds={unclaimedBlockIds}
            onInteraction={handleInteraction}
          />
        )}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
