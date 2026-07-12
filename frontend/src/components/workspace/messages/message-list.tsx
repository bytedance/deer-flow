import type { Message } from "@langchain/langgraph-sdk";
import type { BaseStream } from "@langchain/langgraph-sdk/react";
import {
  ChevronUpIcon,
  GitBranchPlusIcon,
  Loader2Icon,
  MessageCircleIcon,
  MessageSquarePlusIcon,
  RefreshCcwIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { toast } from "sonner";

import {
  Conversation,
  ConversationContent,
  type ConversationProps,
} from "@/components/ai-elements/conversation";
import {
  Reasoning,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { Button } from "@/components/ui/button";
import { extractArtifactsFromThread } from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import {
  deriveHumanInputThreadState,
  extractHumanInputRequest,
  shouldClearPendingHumanInputOnThreadError,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
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
  isHiddenFromUIMessage,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import {
  buildMessageSidecarContext,
  type SidecarContext,
} from "@/core/sidecar";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import {
  derivePendingSubtaskStatus,
  parseSubtaskResult,
} from "@/core/tasks/subtask-result";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { CopyButton } from "../copy-button";
import { useMaybeSidecar } from "../sidecar/context";
import { Tooltip } from "../tooltip";

import {
  HumanInputCard,
  type HumanInputSubmitResult,
} from "./human-input-card";
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

const SELECTION_TOOLBAR_MARGIN = 8;
// Approximate rendered height of the pill (p-1 padding + h-8 button). Used only
// to decide whether the toolbar fits above the selection; exact height isn't
// needed because we flip below when space is tight.
const SELECTION_TOOLBAR_ESTIMATED_HEIGHT = 48;

type SelectionToolbarState = {
  context: SidecarContext;
  x: number;
  y: number;
  placement: "top" | "bottom";
};

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
  testId,
  threadId,
  thread,
  paddingBottom = MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  tokenUsageInlineMode = "off",
  hasMoreHistory,
  loadMoreHistory,
  isHistoryLoading,
  onRegenerateMessage,
  onSubmitHumanInput,
  onBranchTurn,
  canRegenerate = false,
  canBranch = false,
  enableSidecarActions = true,
  sidecarSurface = false,
  initialScroll = "smooth",
  resizeScroll = "smooth",
}: {
  className?: string;
  testId?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
  tokenUsageInlineMode?: TokenUsageInlineMode;
  hasMoreHistory?: boolean;
  loadMoreHistory?: () => void;
  isHistoryLoading?: boolean;
  onRegenerateMessage?: (
    messageId: string,
    supersededMessageIds: string[],
  ) => void | Promise<void>;
  onSubmitHumanInput?: (
    request: HumanInputRequest,
    response: HumanInputResponse,
  ) => HumanInputSubmitResult | Promise<HumanInputSubmitResult>;
  onBranchTurn?: (
    messageId: string,
    messageIds: string[],
  ) => void | Promise<void>;
  canRegenerate?: boolean;
  canBranch?: boolean;
  enableSidecarActions?: boolean;
  sidecarSurface?: boolean;
  initialScroll?: ConversationProps["initial"];
  resizeScroll?: ConversationProps["resize"];
}) {
  const { t } = useI18n();
  const sidecar = useMaybeSidecar();
  const [selectionToolbar, setSelectionToolbar] =
    useState<SelectionToolbarState | null>(null);
  const [turnStartTime, setTurnStartTime] = useState<number | null>(null);
  const prevIsLoading = useRef(thread.isLoading);

  useEffect(() => {
    if (thread.isLoading && !prevIsLoading.current) {
      setTurnStartTime(Date.now());
    }
    prevIsLoading.current = thread.isLoading;
  }, [thread.isLoading]);
  const messages = thread.messages;
  const groupedMessages = getMessageGroups(messages);
  const [regeneratingMessageId, setRegeneratingMessageId] = useState<
    string | null
  >(null);
  const [pendingHumanInputRequestIds, setPendingHumanInputRequestIds] =
    useState<Set<string>>(() => new Set());
  const previousHumanInputThreadError = useRef<unknown>(thread.error);
  const [branchingMessageId, setBranchingMessageId] = useState<string | null>(
    null,
  );
  const hasActiveAssistantText = useMemo(() => {
    let lastHumanIndex = -1;
    for (let i = groupedMessages.length - 1; i >= 0; i--) {
      if (groupedMessages[i]?.type === "human") {
        lastHumanIndex = i;
        break;
      }
    }
    if (lastHumanIndex === -1) return false;
    return groupedMessages
      .slice(lastHumanIndex)
      .some((g) => g.type === "assistant");
  }, [groupedMessages]);
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const lastGroupIndex = groupedMessages.length - 1;
  const turnUsageMessagesByGroupIndex =
    getAssistantTurnUsageMessages(groupedMessages);
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

  const humanInputState = useMemo(
    () =>
      deriveHumanInputThreadState(
        messages,
        (message) => !isHiddenFromUIMessage(message),
      ),
    [messages],
  );

  useEffect(() => {
    if (pendingHumanInputRequestIds.size === 0) {
      return;
    }
    setPendingHumanInputRequestIds((previous) => {
      const next = new Set(previous);
      for (const requestId of previous) {
        if (humanInputState.answeredResponses.has(requestId)) {
          next.delete(requestId);
        }
      }
      return next.size === previous.size ? previous : next;
    });
  }, [humanInputState.answeredResponses, pendingHumanInputRequestIds.size]);

  useEffect(() => {
    const previousError = previousHumanInputThreadError.current;
    previousHumanInputThreadError.current = thread.error;

    if (
      !shouldClearPendingHumanInputOnThreadError({
        currentError: thread.error,
        pendingRequestCount: pendingHumanInputRequestIds.size,
        previousError,
      })
    ) {
      return;
    }

    // `sendMessage` can return after dispatching while the SDK stream later
    // reports an async error through `thread.error`. In that case the hidden
    // human reply never reaches history, so unlock the card for retry.
    setPendingHumanInputRequestIds(new Set());
  }, [pendingHumanInputRequestIds.size, thread.error]);

  const clearPendingHumanInput = useCallback((requestId: string) => {
    setPendingHumanInputRequestIds((previous) => {
      if (!previous.has(requestId)) {
        return previous;
      }
      const next = new Set(previous);
      next.delete(requestId);
      return next;
    });
  }, []);

  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      setPendingHumanInputRequestIds((previous) => {
        const next = new Set(previous);
        next.add(request.request_id);
        return next;
      });

      try {
        const result = await onSubmitHumanInput?.(request, response);
        if (result === false) {
          clearPendingHumanInput(request.request_id);
        }
        return result;
      } catch (error) {
        clearPendingHumanInput(request.request_id);
        toast.error(error instanceof Error ? error.message : String(error));
        return false;
      }
    },
    [clearPendingHumanInput, onSubmitHumanInput],
  );

  const latestAssistantGroupId = useMemo(() => {
    if (thread.isLoading) {
      return null;
    }
    for (let i = groupedMessages.length - 1; i >= 0; i -= 1) {
      const group = groupedMessages[i];
      if (group?.type === "assistant") {
        return group.id;
      }
    }
    return null;
  }, [groupedMessages, thread.isLoading]);

  const clearSelectionToolbar = useCallback(() => {
    setSelectionToolbar(null);
  }, []);

  useEffect(() => {
    if (!selectionToolbar) {
      return;
    }

    const hideOnScroll = () => {
      setSelectionToolbar(null);
    };
    const hideOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectionToolbar(null);
      }
    };

    window.addEventListener("scroll", hideOnScroll, true);
    document.addEventListener("keydown", hideOnEscape);
    return () => {
      window.removeEventListener("scroll", hideOnScroll, true);
      document.removeEventListener("keydown", hideOnEscape);
    };
  }, [selectionToolbar]);

  const handleAssistantTextSelection = useCallback(
    (
      event: MouseEvent<HTMLDivElement>,
      message: Message,
      displayIndex: number,
    ) => {
      if (
        !enableSidecarActions ||
        thread.isLoading ||
        !sidecar ||
        message.type !== "ai"
      ) {
        return;
      }

      const selection = window.getSelection();
      const selectedText = selection?.toString().trim();
      if (
        !selection ||
        selection.isCollapsed ||
        !selectedText ||
        selection.rangeCount === 0
      ) {
        setSelectionToolbar(null);
        return;
      }

      if (!selection.anchorNode || !selection.focusNode) {
        return;
      }

      // Widen containment to the shared assistant-turn container so a selection
      // that spans multiple AI messages within the same turn still yields a
      // toolbar (#3553). Fall back to the per-message wrapper if the turn
      // container can't be found.
      const turnContainer =
        event.currentTarget.closest<HTMLElement>("[data-assistant-turn]") ??
        event.currentTarget;
      if (!turnContainer.contains(selection.anchorNode)) {
        return;
      }
      if (!turnContainer.contains(selection.focusNode)) {
        // The selection leaked into another turn/message; the quote would be
        // ambiguous, so surface a hint instead of failing silently.
        toast.info(t.sidecar.selectionCrossesMessages);
        setSelectionToolbar(null);
        return;
      }

      const nextContext = buildMessageSidecarContext(message, displayIndex, {
        selectedText,
      });
      if (!nextContext) {
        return;
      }

      // The pill is rendered with `-translate-y-full`, so anchoring it at
      // `rect.top` moves it up by its own height. When the selection sits near
      // the viewport top there isn't room above, so flip it below the selection
      // to keep both actions reachable (#3551).
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      const fitsAbove =
        rect.top -
          SELECTION_TOOLBAR_MARGIN -
          SELECTION_TOOLBAR_ESTIMATED_HEIGHT >=
        0;
      setSelectionToolbar({
        context: nextContext,
        x: rect.left + rect.width / 2,
        y: fitsAbove
          ? rect.top - SELECTION_TOOLBAR_MARGIN
          : rect.bottom + SELECTION_TOOLBAR_MARGIN,
        placement: fitsAbove ? "top" : "bottom",
      });
    },
    [
      enableSidecarActions,
      sidecar,
      t.sidecar.selectionCrossesMessages,
      thread.isLoading,
    ],
  );

  const handleAddSelectionToConversation = useCallback(() => {
    if (!selectionToolbar) {
      return;
    }
    // On the sidecar surface, "add to conversation" targets the side chat's
    // own composer (activeReferences) rather than the main composer's quotes,
    // so the selected snippet is attached to the conversation the user is
    // actually reading.
    if (sidecarSurface) {
      sidecar?.openContext(selectionToolbar.context);
    } else {
      sidecar?.addContextToConversation(selectionToolbar.context);
    }
    window.getSelection()?.removeAllRanges();
    setSelectionToolbar(null);
  }, [selectionToolbar, sidecar, sidecarSurface]);

  const handleAskSelectionInSidecar = useCallback(() => {
    if (!selectionToolbar) {
      return;
    }
    sidecar?.openContext(selectionToolbar.context);
    window.getSelection()?.removeAllRanges();
    setSelectionToolbar(null);
  }, [selectionToolbar, sidecar]);

  const renderAssistantActions = useCallback(
    (
      messages: Message[],
      isStreaming: boolean,
      enableRegenerateForTurn: boolean,
    ) => {
      const clipboardData = getAssistantTurnCopyData(messages, { isStreaming });
      const actionTarget = [...messages]
        .reverse()
        .find((message) => message.type === "ai" && message.id);
      const assistantMessageIds = messages
        .filter((message) => message.type === "ai" && message.id)
        .map((message) => message.id)
        .filter((id): id is string => typeof id === "string");
      if (!clipboardData && !actionTarget) {
        return null;
      }

      return (
        <div className="mt-2 flex justify-start gap-1 opacity-0 transition-opacity delay-200 duration-300 group-hover/assistant-turn:opacity-100">
          {clipboardData && <CopyButton clipboardData={clipboardData} />}
          {!isStreaming && actionTarget?.id && onBranchTurn && (
            <Tooltip content={t.common.branch}>
              <Button
                aria-label={t.common.branch}
                size="icon-sm"
                type="button"
                variant="ghost"
                disabled={!canBranch || branchingMessageId === actionTarget.id}
                onClick={() => {
                  const targetId = actionTarget.id;
                  if (!targetId) {
                    return;
                  }
                  setBranchingMessageId(targetId);
                  void Promise.resolve(
                    onBranchTurn(targetId, assistantMessageIds),
                  ).finally(() => {
                    setBranchingMessageId(null);
                  });
                }}
              >
                <GitBranchPlusIcon
                  className={cn(
                    "size-4",
                    branchingMessageId === actionTarget.id && "animate-pulse",
                  )}
                />
              </Button>
            </Tooltip>
          )}
          {enableRegenerateForTurn &&
            actionTarget?.id &&
            onRegenerateMessage && (
              <Tooltip content={t.common.regenerate}>
                <Button
                  aria-label={t.common.regenerate}
                  size="icon-sm"
                  type="button"
                  variant="ghost"
                  disabled={
                    !canRegenerate || regeneratingMessageId === actionTarget.id
                  }
                  onClick={() => {
                    const targetId = actionTarget.id;
                    if (!targetId) {
                      return;
                    }
                    setRegeneratingMessageId(targetId);
                    void Promise.resolve(
                      onRegenerateMessage?.(targetId, assistantMessageIds),
                    ).finally(() => {
                      setRegeneratingMessageId(null);
                    });
                  }}
                >
                  <RefreshCcwIcon
                    className={cn(
                      "size-3",
                      regeneratingMessageId === actionTarget.id &&
                        "animate-spin",
                    )}
                  />
                </Button>
              </Tooltip>
            )}
        </div>
      );
    },
    [
      branchingMessageId,
      canBranch,
      canRegenerate,
      onBranchTurn,
      onRegenerateMessage,
      regeneratingMessageId,
      t.common.branch,
      t.common.regenerate,
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

  const artifactPaths = extractArtifactsFromThread(thread);

  return (
    <>
      <Conversation
        className={cn("flex size-full flex-col justify-center", className)}
        data-testid={testId}
        initial={initialScroll}
        resize={resizeScroll}
      >
        <ConversationContent className="mx-auto w-full max-w-(--container-width-md) gap-8 pt-8">
          <LoadMoreHistoryIndicator
            isLoading={isHistoryLoading}
            hasMore={hasMoreHistory}
            loadMore={loadMoreHistory}
          />
          {groupedMessages.map((group, groupIndex) => {
            const turnUsageMessages = turnUsageMessagesByGroupIndex[groupIndex];
            const groupIsLoading =
              thread.isLoading && groupIndex === lastGroupIndex;

            if (group.type === "human" || group.type === "assistant") {
              return (
                <div
                  key={group.id}
                  data-assistant-turn={
                    group.type === "assistant" ? "" : undefined
                  }
                  className={cn(
                    "w-full",
                    group.type === "assistant" && "group/assistant-turn",
                  )}
                >
                  {group.messages.map((msg) => {
                    const item = (
                      <MessageListItem
                        message={msg}
                        isLoading={
                          thread.isLoading &&
                          groupIndex === groupedMessages.length - 1
                        }
                        threadId={threadId}
                        artifactPaths={artifactPaths}
                        runId={
                          group.type === "assistant"
                            ? (msg as { run_id?: string }).run_id
                            : undefined
                        }
                        showCopyButton={group.type !== "assistant"}
                        turnStartTime={
                          groupIndex === groupedMessages.length - 1
                            ? turnStartTime
                            : null
                        }
                      />
                    );

                    if (
                      group.type !== "assistant" ||
                      !enableSidecarActions ||
                      msg.type !== "ai"
                    ) {
                      return <div key={`${group.id}/${msg.id}`}>{item}</div>;
                    }

                    return (
                      <div
                        key={`${group.id}/${msg.id}`}
                        onMouseUp={(event) =>
                          handleAssistantTextSelection(
                            event,
                            msg,
                            groupIndex + 1,
                          )
                        }
                      >
                        {item}
                      </div>
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
                      group.id === latestAssistantGroupId,
                    )}
                </div>
              );
            } else if (group.type === "assistant:clarification") {
              const message = group.messages[0];
              if (!message) {
                return null;
              }

              const humanInputRequest = extractHumanInputRequest(message);
              if (humanInputRequest) {
                const answeredResponse =
                  humanInputState.answeredResponses.get(
                    humanInputRequest.request_id,
                  ) ?? null;
                const pending = pendingHumanInputRequestIds.has(
                  humanInputRequest.request_id,
                );
                return (
                  <div key={group.id} className="w-full">
                    <HumanInputCard
                      answeredResponse={answeredResponse}
                      disabled={
                        thread.isLoading ||
                        pending ||
                        Boolean(answeredResponse) ||
                        humanInputState.latestOpenRequestId !==
                          humanInputRequest.request_id ||
                        !onSubmitHumanInput
                      }
                      pending={pending}
                      request={humanInputRequest}
                      onSubmit={
                        onSubmitHumanInput
                          ? (response) =>
                              handleSubmitHumanInput(
                                humanInputRequest,
                                response,
                              )
                          : undefined
                      }
                    />
                    {renderTokenUsage({
                      messages: group.messages,
                      turnUsageMessages,
                    })}
                  </div>
                );
              }

              if (hasContent(message)) {
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
                      const taskId = toolCall.id;
                      if (!taskId) {
                        continue;
                      }
                      const status = derivePendingSubtaskStatus(
                        taskId,
                        group.messages,
                        groupIsLoading,
                      );
                      const task: Subtask = {
                        id: taskId,
                        subagent_type: toolCall.args.subagent_type,
                        description: toolCall.args.description,
                        prompt: toolCall.args.prompt,
                        status,
                        ...(status === "failed"
                          ? { error: t.subtasks.failed }
                          : {}),
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
                      message.additional_kwargs,
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
                      isLoading={groupIsLoading}
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
                const taskIds = message.tool_calls?.flatMap((toolCall) =>
                  toolCall.name === "task" && toolCall.id ? [toolCall.id] : [],
                );
                for (const taskId of taskIds ?? []) {
                  results.push(
                    <SubtaskCard
                      key={"task-group-" + taskId}
                      taskId={taskId}
                      threadId={threadId}
                      runId={(message as { run_id?: string }).run_id}
                      isLoading={groupIsLoading}
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
                  showTokenDebugSummaries={
                    tokenUsageInlineMode === "step_debug"
                  }
                />
                {renderTokenUsage({
                  messages: group.messages,
                  turnUsageMessages,
                  inlineDebug: false,
                })}
              </div>
            );
          })}
          {thread.isLoading && !hasActiveAssistantText && (
            <div className="w-full">
              <Reasoning isStreaming={true} startTimeProp={turnStartTime}>
                <ReasoningTrigger hasContent={false} />
              </Reasoning>
            </div>
          )}
          <div style={{ height: `${paddingBottom}px` }} />
        </ConversationContent>
      </Conversation>
      {selectionToolbar && sidecar && (
        <div
          className={cn(
            "bg-popover text-popover-foreground border-border fixed z-50 flex -translate-x-1/2 items-center gap-1 rounded-full border p-1 shadow-lg",
            selectionToolbar.placement === "bottom"
              ? "translate-y-0"
              : "-translate-y-full",
          )}
          data-sidecar-selection-toolbar
          style={{ left: selectionToolbar.x, top: selectionToolbar.y }}
        >
          <Button
            className="h-8 rounded-full px-2.5 text-xs"
            size="sm"
            type="button"
            variant="ghost"
            onClick={handleAddSelectionToConversation}
            onMouseDown={(event) => event.preventDefault()}
          >
            <MessageCircleIcon className="size-3.5" />
            {t.sidecar.addToConversation}
          </Button>
          {!sidecarSurface && (
            <Button
              className="h-8 rounded-full px-2.5 text-xs"
              size="sm"
              type="button"
              variant="ghost"
              onClick={handleAskSelectionInSidecar}
              onMouseDown={(event) => event.preventDefault()}
            >
              <MessageSquarePlusIcon className="size-3.5" />
              {t.sidecar.askInSideChat}
            </Button>
          )}
          <Button
            aria-label={t.common.close}
            className="size-8 rounded-full"
            size="icon-sm"
            type="button"
            variant="ghost"
            onClick={clearSelectionToolbar}
            onMouseDown={(event) => event.preventDefault()}
          >
            <span aria-hidden="true">×</span>
          </Button>
        </div>
      )}
    </>
  );
}
