import type { AIMessage, Message, Run } from "@langchain/langgraph-sdk";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { GenUISSEManager } from "@/core/genui/sse-recovery";
import { type UIBlock, useBlockStore } from "@/core/genui/store";
import { useUIBlockExtractor } from "@/core/genui/use-ui-block-extractor";
import { useDocumentVisible } from "@/hooks/use-document-visible";

import { fetchGateway, getAPIClient } from "../api";
import { getBackendBaseURL } from "../config";
import { useI18n } from "../i18n/hooks";
import type { FileInMessage } from "../messages/utils";
import type { ArtifactStatus, UploadStatus } from "../models/status";
import type { LocalSettings } from "../settings";
import { useUpdateSubtask } from "../tasks/context";
import { getCurrentTenantId } from "../tenant";
import type { UploadedFileInfo } from "../uploads";
import { promptInputFilePartToFile, uploadFiles } from "../uploads";

import { appendUniqueMessages } from "./message-history";
import type { AgentThread, AgentThreadState, RunMessage } from "./types";
import { useHasActiveRun } from "./use-has-active-run";
import { useStreamModes } from "./use-stream-tier";
import { useRegisterActiveStream } from "./use-active-stream-count";

export type ToolEndEvent = {
  name: string;
  data: unknown;
};

export type ThreadStreamOptions = {
  threadId?: string | null | undefined;
  context: LocalSettings["context"];
  isMock?: boolean;
  onSend?: (threadId: string) => void;
  onStart?: (threadId: string, runId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
};

type SendMessageOptions = {
  additionalKwargs?: Record<string, unknown>;
  interactionRetryAttempt?: number;
};

function getModelText(
  text: string,
  additionalKwargs: Record<string, unknown> | undefined,
): string {
  const modelText = additionalKwargs?.model_text;
  return typeof modelText === "string" && modelText.trim() ? modelText : text;
}

function getSubmitAdditionalKwargs(
  additionalKwargs: Record<string, unknown> | undefined,
  filesForSubmit: FileInMessage[],
  displayText: string,
): Record<string, unknown> {
  const result = { ...(additionalKwargs ?? {}) };
  delete result.model_text;
  return {
    ...result,
    display_text:
      typeof result.display_text === "string" ? result.display_text : displayText,
    ...(filesForSubmit.length > 0 ? { files: filesForSubmit } : {}),
  };
}

const UI_INTERACTION_RETRY_DELAY_MS = 300;
const UI_INTERACTION_MAX_RETRY_ATTEMPTS = 60;


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isHiddenUiInteractionMessage(
  text: string,
  options?: SendMessageOptions,
): boolean {
  if (options?.additionalKwargs?.hide_from_ui !== true) {
    return false;
  }
  try {
    const parsed = JSON.parse(text);
    return isRecord(parsed) && parsed.type === "ui_interaction";
  } catch {
    return false;
  }
}

function mergeMessages(
  historyMessages: Message[],
  threadMessages: Message[],
  optimisticMessages: Message[],
): Message[] {
  const threadMessageIds = new Set(
    threadMessages
      .map((m) => ("tool_call_id" in m ? m.tool_call_id : m.id))
      .filter(Boolean),
  );

  // The overlap is a contiguous suffix of historyMessages (newest history == oldest thread).
  // Scan from the end: shrink cutoff while messages are already in thread, stop as soon as
  // we hit one that isn't — everything before that point is non-overlapping.
  let cutoff = historyMessages.length;
  for (let i = historyMessages.length - 1; i >= 0; i--) {
    const msg = historyMessages[i];
    if (!msg) {
      continue;
    }
    if (
      (msg?.id && threadMessageIds.has(msg.id)) ||
      ("tool_call_id" in msg && threadMessageIds.has(msg.tool_call_id))
    ) {
      cutoff = i;
    } else {
      break;
    }
  }

  return [
    ...historyMessages.slice(0, cutoff),
    ...threadMessages,
    ...optimisticMessages,
  ];
}

function getStreamErrorMessage(error: unknown): string {
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === "object" && error !== null) {
    const message = Reflect.get(error, "message");
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    const nestedError = Reflect.get(error, "error");
    if (nestedError instanceof Error && nestedError.message.trim()) {
      return nestedError.message;
    }
    if (typeof nestedError === "string" && nestedError.trim()) {
      return nestedError;
    }
  }
  return "Request failed.";
}

/** Extract failure metadata from a structured stream error for layer-aware display. */
function extractFailureMeta(
  error: unknown,
): { category: string | null; layer: string | null } {
  if (typeof error === "object" && error !== null) {
    const category = Reflect.get(error, "failure_category");
    const layer = Reflect.get(error, "failed_layer");
    return {
      category: typeof category === "string" ? category : null,
      layer: typeof layer === "string" ? layer : null,
    };
  }
  return { category: null, layer: null };
}

interface QuotaErrorDetail {
  code: "quota_daily_exceeded" | "quota_monthly_exceeded";
  used: number;
  limit: number;
  period: "daily" | "monthly";
}

function extractQuotaError(error: unknown): QuotaErrorDetail | null {
  if (typeof error !== "object" || error === null) return null;

  let detail = Reflect.get(error, "detail");

  if (detail === undefined || detail === null) {
    const text = Reflect.get(error, "text");
    if (typeof text === "string") {
      try {
        const parsed = JSON.parse(text);
        detail = parsed?.detail;
      } catch {
        // Malformed JSON — fall through
      }
    }
  }

  if (typeof detail !== "object" || detail === null) return null;

  const code = Reflect.get(detail, "code");
  if (code === "quota_daily_exceeded" || code === "quota_monthly_exceeded") {
    return {
      code,
      used: Number(Reflect.get(detail, "used")) || 0,
      limit: Number(Reflect.get(detail, "limit")) || 0,
      period: Reflect.get(detail, "period") as "daily" | "monthly",
    };
  }
  return null;
}

export function useThreadStream({
  threadId,
  context,
  isMock,
  onSend,
  onStart,
  onFinish,
  onToolEnd,
}: ThreadStreamOptions) {
  const { t } = useI18n();
  const requestedThreadId = threadId ?? null;
  // Track the thread ID that is currently streaming to handle thread changes during streaming
  const [onStreamThreadId, setOnStreamThreadId] = useState(() => threadId);
  // Ref to track current thread ID across async callbacks without causing re-renders,
  // and to allow access to the current thread id in onUpdateEvent
  const threadIdRef = useRef<string | null>(threadId ?? null);
  const startedRef = useRef(false);
  const sseManagerRef = useRef<GenUISSEManager | null>(null);
  const lastSequenceRef = useRef<number>(0);
  const listeners = useRef({
    onSend,
    onStart,
    onFinish,
    onToolEnd,
  });

  const {
    messages: history,
    hasMore: hasMoreHistory,
    loadMore: loadMoreHistory,
    loading: isHistoryLoading,
    appendMessages,
  } = useThreadHistory(requestedThreadId ?? "");

  // Keep listeners ref updated with latest callbacks
  useEffect(() => {
    listeners.current = { onSend, onStart, onFinish, onToolEnd };
  }, [onSend, onStart, onFinish, onToolEnd]);

  const prevThreadIdRef = useRef<string | null>(null);

  useEffect(() => {
    const normalizedThreadId = requestedThreadId;
    const prevThreadId = prevThreadIdRef.current;
    prevThreadIdRef.current = normalizedThreadId;

    if (!normalizedThreadId) {
      // Reset when the UI moves back to a brand new unsaved thread.
      startedRef.current = false;
      setOnStreamThreadId(normalizedThreadId);
      useBlockStore.getState().reset();
    } else {
      setOnStreamThreadId(normalizedThreadId);
      if (prevThreadId !== normalizedThreadId) {
        useBlockStore.getState().reset();
      }
    }
    useBlockStore.getState().setActiveThread(normalizedThreadId);
    threadIdRef.current = normalizedThreadId;

    sseManagerRef.current?.disconnect();
    if (normalizedThreadId) {
      const manager = new GenUISSEManager(normalizedThreadId);
      sseManagerRef.current = manager;
      void manager.recoverBlocks();
    } else {
      sseManagerRef.current = null;
    }

    return () => {
      sseManagerRef.current?.disconnect();
    };
  }, [requestedThreadId]);

  const handleStreamStart = useCallback((_threadId: string, _runId: string) => {
    threadIdRef.current = _threadId;
    lastSequenceRef.current = 0;
    setBackgroundPaused(false);
    setBackgroundError(null);
    backgroundErrorRef.current = null;
    if (!startedRef.current) {
      listeners.current.onStart?.(_threadId, _runId);
      startedRef.current = true;
    }
    setOnStreamThreadId(_threadId);
  }, []);

  const queryClient = useQueryClient();
  const updateSubtask = useUpdateSubtask();

  function trackSequence(data: unknown): void {
    if (!data || typeof data !== "object" || Array.isArray(data)) return;
    const seq = (data as Record<string, unknown>)._seq;
    if (typeof seq !== "number") return;
    if (lastSequenceRef.current > 0 && seq > lastSequenceRef.current + 1) {
      const tid = threadIdRef.current;
      if (tid) {
        void queryClient.invalidateQueries({ queryKey: ["thread", tid] });
      }
    }
    lastSequenceRef.current = seq;
  }

  const isVisible = useDocumentVisible();
  const hasActiveRun = useHasActiveRun(onStreamThreadId);
  const streamModes = useStreamModes();
  const reconnectOnMount = isVisible && hasActiveRun;

  useEffect(() => {
    sseManagerRef.current?.setVisibility(isVisible);
  }, [isVisible]);

  const thread = useStream<AgentThreadState>({
    client: getAPIClient(isMock),
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    throttle: 100,
    reconnectOnMount,
    fetchStateHistory: { limit: 1 },
    onCreated(meta) {
      handleStreamStart(meta.thread_id, meta.run_id);
      if (context.agent_name && !isMock) {
        void getAPIClient()
          .threads.update(meta.thread_id, {
            metadata: { agent_name: context.agent_name },
          })
          .catch(() => ({}));
      }
    },
    onCustomEvent(event: unknown) {
      trackSequence(event);
      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event &&
        event.type === "state_patch"
      ) {
        const e = event as {
          type: "state_patch";
          patch: Partial<AgentThreadState>;
        };
        const patch = e.patch;
        if (patch && threadIdRef.current) {
          void queryClient.setQueriesData(
            { queryKey: ["threads", "search"], exact: false },
            (oldData: Array<AgentThread> | undefined) => {
              return oldData?.map((t) => {
                if (t.thread_id === threadIdRef.current) {
                  return { ...t, values: { ...t.values, ...patch } };
                }
                return t;
              });
            },
          );
          void queryClient.setQueryData(
            ["thread", threadIdRef.current],
            (old: AgentThread | undefined) => {
              if (!old) return old;
              return { ...old, values: { ...old.values, ...patch } };
            },
          );
        }
        return;
      }

      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event &&
        event.type === "tool_end"
      ) {
        const e = event as { type: "tool_end"; name: string; data: unknown };
        listeners.current.onToolEnd?.({ name: e.name, data: e.data });
        return;
      }

      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event &&
        event.type === "ui_blocks_folded"
      ) {
        const e = event as { type: "ui_blocks_folded"; blocks: UIBlock[] };
        useBlockStore.getState().replaceAllBlocks(threadIdRef.current ?? "", e.blocks);
        return;
      }

      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event &&
        event.type === "task_running"
      ) {
        const e = event as {
          type: "task_running";
          task_id: string;
          message: AIMessage;
        };
        updateSubtask({ id: e.task_id, latestMessage: e.message });
        return;
      }

      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event &&
        event.type === "llm_retry" &&
        "message" in event &&
        typeof event.message === "string" &&
        event.message.trim()
      ) {
        const e = event as { type: "llm_retry"; message: string };
        toast(e.message);
      }
    },
    onUpdateEvent(data) {
      trackSequence(data);
      if (data["SummarizationMiddleware.before_model"]) {
        const _messages = [
          ...(data["SummarizationMiddleware.before_model"].messages ?? []),
        ];

        if (_messages.length < 2) {
          return;
        }
        for (const m of _messages) {
          if (m.name === "summary" && m.type === "human") {
            summarizedRef.current?.add(m.id ?? "");
          }
        }
        const _lastKeepMessage = _messages[2];
        const _currentMessages = [...messagesRef.current];
        const _movedMessages: Message[] = [];
        for (const m of _currentMessages) {
          if (m.id !== undefined && m.id === _lastKeepMessage?.id) {
            break;
          }
          if (!summarizedRef.current?.has(m.id ?? "")) {
            _movedMessages.push(m);
          }
        }
        appendMessages(_movedMessages);
        messagesRef.current = [];
      }

      const updates = [data, ...Object.values(data || {})].filter(isRecord);
      for (const update of updates) {
        if (typeof update.title === "string" && update.title) {
          void queryClient.setQueriesData(
            {
              queryKey: ["threads", "search"],
              exact: false,
            },
            (oldData: Array<AgentThread> | undefined) => {
              return oldData?.map((t) => {
                if (t.thread_id === threadIdRef.current) {
                  return {
                    ...t,
                    values: {
                      ...t.values,
                      title: update.title,
                    },
                  };
                }
                return t;
              });
            },
          );
        }
      }
    },
    onError(error) {
      setOptimisticMessages([]);
      if (backgroundPaused) {
        backgroundErrorRef.current = error;
        sseManagerRef.current?.scheduleReconnect();
        return;
      }
      const quotaError = extractQuotaError(error);
      if (quotaError) {
        const message =
          quotaError.code === "quota_daily_exceeded"
            ? t.errors.quota_daily_exceeded(quotaError.used, quotaError.limit)
            : t.errors.quota_monthly_exceeded(quotaError.used, quotaError.limit);
        toast.error(message);
      } else {
        const message = getStreamErrorMessage(error);
        const { category, layer } = extractFailureMeta(error);
        if (category === "external_dependency_unavailable") {
          toast.error(message, { description: "外部服务暂不可用，请稍后重试" });
        } else {
          toast.error(message);
        }
      }
      sseManagerRef.current?.scheduleReconnect();
    },
    onFinish(state) {
      onFinishFiredRef.current = true;
      appendMessages(messagesRef.current);
      listeners.current.onFinish?.(state.values);
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      if (threadIdRef.current) {
        void queryClient.invalidateQueries({
          queryKey: ["thread", threadIdRef.current],
        });
      }
    },
  });

  useRegisterActiveStream(thread.isLoading);

  const wasVisibleRef = useRef(true);
  const wasLoadingBeforeHideRef = useRef(false);
  const onFinishFiredRef = useRef(false);
  const backgroundErrorRef = useRef<unknown | null>(null);
  const [backgroundPaused, setBackgroundPaused] = useState(false);
  const [backgroundError, setBackgroundError] = useState<unknown | null>(null);

  useEffect(() => {
    if (!isVisible && wasVisibleRef.current) {
      wasLoadingBeforeHideRef.current = thread.isLoading;
      onFinishFiredRef.current = false;
      if (thread.isLoading) {
        setBackgroundPaused(true);
      }
    }
    if (isVisible && !wasVisibleRef.current) {
      setBackgroundPaused(false);
      const bgError = backgroundErrorRef.current;
      backgroundErrorRef.current = null;
      if (bgError !== null) {
        setBackgroundError(bgError);
      }
      if (wasLoadingBeforeHideRef.current && !thread.isLoading && !onFinishFiredRef.current) {
        onFinishFiredRef.current = true;
        appendMessages(messagesRef.current);
        listeners.current.onFinish?.(thread.messages as unknown as AgentThreadState);
        void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
        if (threadIdRef.current) {
          void queryClient.invalidateQueries({
            queryKey: ["thread", threadIdRef.current],
          });
        }
      }
    }
    wasVisibleRef.current = isVisible;
  }, [isVisible, thread.isLoading, appendMessages, queryClient, thread.messages]);

  // Optimistic messages shown before the server stream responds
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const sendInFlightRef = useRef(false);
  const messagesRef = useRef<Message[]>([]);
  const summarizedRef = useRef<Set<string>>(null);
  // Track message count before sending so we know when server has responded
  const prevMsgCountRef = useRef(thread.messages.length);

  summarizedRef.current ??= new Set<string>();

  // Reset thread-local pending UI state when switching between threads so
  // optimistic messages and in-flight guards do not leak across chat views.
  useEffect(() => {
    startedRef.current = false;
    sendInFlightRef.current = false;
    setOptimisticMessages([]);
    setIsUploading(false);
    messagesRef.current = [];
    summarizedRef.current = new Set();
    prevMsgCountRef.current = 0;
    setBackgroundPaused(false);
    setBackgroundError(null);
    backgroundErrorRef.current = null;
  }, [threadId]);

  // Clear optimistic when server messages arrive (count increases)
  useEffect(() => {
    if (
      optimisticMessages.length > 0 &&
      thread.messages.length > prevMsgCountRef.current
    ) {
      setOptimisticMessages([]);
    }
  }, [thread.messages.length, optimisticMessages.length]);

  const sendMessage = useCallback(
    async (
      threadId: string,
      message: PromptInputMessage,
      extraContext?: Record<string, unknown>,
      options?: SendMessageOptions,
    ) => {
      const text = message.text.trim();
      const shouldRetryUiInteraction = isHiddenUiInteractionMessage(text, options);

      if (sendInFlightRef.current) {
        if (shouldRetryUiInteraction) {
          const retryAttempt = options?.interactionRetryAttempt ?? 0;
          if (retryAttempt < UI_INTERACTION_MAX_RETRY_ATTEMPTS) {
            window.setTimeout(() => {
              void sendMessage(threadId, message, extraContext, {
                ...options,
                interactionRetryAttempt: retryAttempt + 1,
              });
            }, UI_INTERACTION_RETRY_DELAY_MS);
          } else {
            toast.error("交互提交已收到，但线程暂时忙碌，未能继续执行。请稍后重试。");
          }
        }
        return;
      }
      sendInFlightRef.current = true;

      const modelText = getModelText(text, options?.additionalKwargs);

      // Capture current count before showing optimistic messages
      prevMsgCountRef.current = thread.messages.length;

      // Build optimistic files list with uploading status
      const optimisticFiles: FileInMessage[] = (message.files ?? []).map(
        (f) => ({
          filename: f.filename ?? "",
          size: 0,
          status: "uploading" satisfies UploadStatus,
        }),
      );

      const hideFromUI = options?.additionalKwargs?.hide_from_ui === true;
      const optimisticAdditionalKwargs = {
        ...options?.additionalKwargs,
        ...(optimisticFiles.length > 0 ? { files: optimisticFiles } : {}),
      };

      const newOptimistic: Message[] = [];
      if (!hideFromUI) {
        newOptimistic.push({
          type: "human",
          id: `opt-human-${Date.now()}`,
          content: text ? [{ type: "text", text }] : "",
          additional_kwargs: optimisticAdditionalKwargs,
        });
      }

      if (optimisticFiles.length > 0 && !hideFromUI) {
        // Mock AI message while files are being uploaded
        newOptimistic.push({
          type: "ai",
          id: `opt-ai-${Date.now()}`,
          content: t.uploads.uploadingFiles,
          additional_kwargs: { element: "task" },
        });
      }
      setOptimisticMessages(newOptimistic);

      listeners.current.onSend?.(threadId);

      let uploadedFileInfo: UploadedFileInfo[] = [];

      try {
        // Upload files first if any
        if (message.files && message.files.length > 0) {
          setIsUploading(true);
          try {
            const filePromises = message.files.map((fileUIPart) =>
              promptInputFilePartToFile(fileUIPart),
            );

            const conversionResults = await Promise.all(filePromises);
            const files = conversionResults.filter(
              (file): file is File => file !== null,
            );
            const failedConversions = conversionResults.length - files.length;

            if (failedConversions > 0) {
              throw new Error(
                `Failed to prepare ${failedConversions} attachment(s) for upload. Please retry.`,
              );
            }

            if (!threadId) {
              throw new Error("Thread is not ready for file upload.");
            }

            if (files.length > 0) {
              const uploadResponse = await uploadFiles(threadId, files);
              uploadedFileInfo = uploadResponse.files;

              // Update optimistic human message with uploaded status + paths
              const uploadedFiles: FileInMessage[] = uploadedFileInfo.map(
                (info) => ({
                  filename: info.filename,
                  size: info.size,
                  path: info.virtual_path,
                  status: "ready" satisfies UploadStatus,
                }),
              );
              setOptimisticMessages((messages) => {
                if (messages.length > 1 && messages[0]) {
                  const humanMessage: Message = messages[0];
                  return [
                    {
                      ...humanMessage,
                      additional_kwargs: { files: uploadedFiles },
                    },
                    ...messages.slice(1),
                  ];
                }
                return messages;
              });
            }
          } catch (error) {
            const errorMessage =
              error instanceof Error
                ? error.message
                : "Failed to upload files.";
            toast.error(errorMessage);
            setOptimisticMessages([]);
            throw error;
          } finally {
            setIsUploading(false);
          }
        }

        // Build files metadata for submission (included in additional_kwargs)
        const filesForSubmit: FileInMessage[] = uploadedFileInfo.map(
          (info) => ({
            filename: info.filename,
            size: info.size,
            path: info.virtual_path,
            status: "ready" satisfies UploadStatus,
          }),
        );

        await thread.submit(
          {
            messages: [
              {
                type: "human",
                content: [
                  {
                    type: "text",
                    text: modelText,
                  },
                ],
                additional_kwargs: getSubmitAdditionalKwargs(
                  options?.additionalKwargs,
                  filesForSubmit,
                  text,
                ),
              },
            ],
          },
          {
            threadId: threadId,
            streamMode: [...streamModes],
            streamSubgraphs: context.mode === "ultra",
            streamResumable: true,
            config: {
              recursion_limit: 1000,
            },
            context: {
              ...extraContext,
              ...context,
              thinking_enabled: context.mode !== "flash",
              is_plan_mode: context.mode === "pro" || context.mode === "ultra",
              subagent_enabled: context.mode === "ultra",
              reasoning_effort:
                context.reasoning_effort ??
                (context.mode === "ultra"
                  ? "high"
                  : context.mode === "pro"
                    ? "medium"
                    : context.mode === "thinking"
                      ? "low"
                      : undefined),
              thread_id: threadId,
              tenant_id: getCurrentTenantId(),
            },
          },
        );
        void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      } catch (error) {
        setOptimisticMessages([]);
        setIsUploading(false);
        throw error;
      } finally {
        sendInFlightRef.current = false;
      }
    },
    [thread, t.uploads.uploadingFiles, context, queryClient],
  );

  // Cache the latest thread messages in a ref to compare against incoming history messages for deduplication,
  // and to allow access to the full message list in onUpdateEvent without causing re-renders.
  if (thread.messages.length >= messagesRef.current.length) {
    messagesRef.current = thread.messages;
  }

  // Retain the last non-empty values across thread switches so that fields like
  // `todos` don't flash empty while the SDK reloads history for the new thread.
  // The ref is cleared once the new thread's history finishes loading.
  const lastValuesRef = useRef<Record<string, unknown>>({});
  if (thread.values && Object.keys(thread.values).length > 0 && !thread.isThreadLoading) {
    lastValuesRef.current = thread.values;
  } else if (!thread.isThreadLoading) {
    lastValuesRef.current = {};
  }

  const isThreadSwitchPending =
    requestedThreadId !== onStreamThreadId &&
    !(requestedThreadId === null && prevThreadIdRef.current === null);
  const visibleHistory = isThreadSwitchPending ? [] : history;
  const visibleThreadMessages = isThreadSwitchPending ? [] : thread.messages;
  const visibleOptimisticMessages = isThreadSwitchPending
    ? []
    : optimisticMessages;

  const mergedMessages = mergeMessages(
    visibleHistory,
    visibleThreadMessages,
    visibleOptimisticMessages,
  );

  useUIBlockExtractor(onStreamThreadId, mergedMessages, thread.isLoading);

  // Merge history, live stream, and optimistic messages for display
  // History messages may overlap with thread.messages; thread.messages take precedence
  const valuesForDisplay =
    thread.values && Object.keys(thread.values).length > 0
      ? thread.values
      : lastValuesRef.current;

  const mergedThread = {
    ...thread,
    values: valuesForDisplay,
    isLoading: isThreadSwitchPending ? false : thread.isLoading,
    error: isThreadSwitchPending ? null : (thread.error ?? backgroundError),
    messages: mergedMessages,
    backgroundPaused: isThreadSwitchPending ? false : backgroundPaused,
    backgroundError: isThreadSwitchPending ? null : backgroundError,
  } as typeof thread & { backgroundPaused: boolean; backgroundError: unknown | null };

  return {
    thread: mergedThread,
    sendMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } as const;
}

export function useThreadHistory(threadId: string) {
  const runs = useThreadRuns(threadId);
  const threadIdRef = useRef(threadId);
  const runsRef = useRef(runs.data ?? []);
  const indexRef = useRef(-1);
  const loadingRef = useRef(false);
  const initializedRef = useRef(false);
  const loadedRunIdsRef = useRef<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);

  loadingRef.current = loading;
  const loadMessages = useCallback(async () => {
    if (runsRef.current.length === 0) {
      return;
    }
    const run = runsRef.current[indexRef.current];
    if (!run || loadingRef.current) {
      return;
    }
    if (loadedRunIdsRef.current.has(run.run_id)) {
      indexRef.current -= 1;
      return;
    }
    const requestThreadId = threadIdRef.current;
    const requestRunId = run.run_id;
    try {
      setLoading(true);
      loadedRunIdsRef.current.add(run.run_id);
      const result: { data: RunMessage[]; hasMore: boolean } = await fetch(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(requestThreadId)}/runs/${encodeURIComponent(requestRunId)}/messages`,
        {
          method: "GET",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
        },
      ).then((res) => {
        return res.json();
      });
      const _messages = result.data
        .filter((m) => !m.metadata.caller?.startsWith("middleware:"))
        .map((m) => m.content);
      if (threadIdRef.current !== requestThreadId) {
        return;
      }
      setMessages((prev) => appendUniqueMessages(prev, _messages, "prepend"));
      indexRef.current -= 1;
    } catch (err) {
      console.error(err);
      if (threadIdRef.current === requestThreadId) {
        loadedRunIdsRef.current.delete(requestRunId);
      }
    } finally {
      if (threadIdRef.current === requestThreadId) {
        setLoading(false);
      }
    }
  }, []);
  useEffect(() => {
    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      initializedRef.current = false;
      loadedRunIdsRef.current = new Set();
      runsRef.current = [];
      indexRef.current = -1;
      setLoading(false);
      setMessages([]);
    }
    if (runs.data && runs.data.length > 0) {
      runsRef.current = runs.data ?? [];
      if (!initializedRef.current) {
        initializedRef.current = true;
        indexRef.current = runs.data.length - 1;
        loadMessages().catch(() => {
          toast.error("Failed to load thread history.");
        });
      }
    }
  }, [threadId, runs.data, loadMessages]);

  const appendMessages = useCallback((_messages: Message[]) => {
    setMessages((prev) => appendUniqueMessages(prev, _messages, "append"));
  }, []);
  const hasMore = indexRef.current >= 0 || !runs.data;
  return {
    runs: runs.data,
    messages,
    loading,
    appendMessages,
    hasMore,
    loadMore: loadMessages,
  };
}

export function useThreads(
  params: {
    limit?: number;
    offset?: number;
    status?: string;
    metadata?: Record<string, unknown>;
  } = {
    limit: 50,
  },
) {
  return useQuery<AgentThread[]>({
    queryKey: ["threads", "search", params],
    queryFn: async () => {
      const body: Record<string, unknown> = {
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      };
      if (params.status) body.status = params.status;
      if (params.metadata) body.metadata = params.metadata;

      const response = await fetchGateway(
        `${getBackendBaseURL()}/api/threads/search`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );

      if (!response.ok) {
        throw new Error("Failed to fetch threads");
      }

      return response.json() as Promise<AgentThread[]>;
    },
    refetchOnWindowFocus: false,
  });
}

export function useThreadRuns(threadId?: string) {
  const apiClient = getAPIClient();
  return useQuery<Run[]>({
    queryKey: ["thread", threadId],
    queryFn: async () => {
      if (!threadId) {
        return [];
      }
      const response = await apiClient.runs.list(threadId);
      return response;
    },
    refetchOnWindowFocus: false,
  });
}

export function useDeleteThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ threadId }: { threadId: string }) => {
      const response = await fetchGateway(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
        {
          method: "DELETE",
        },
      );

      if (!response.ok && response.status !== 404) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Failed to delete thread." }));
        throw new Error(error.detail ?? "Failed to delete thread.");
      }
    },
    onSuccess(_, { threadId }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          if (oldData == null) {
            return oldData;
          }
          return oldData.filter((t) => t.thread_id !== threadId);
        },
      );
    },
    onSettled() {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });
}

export function useRenameThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      title,
    }: {
      threadId: string;
      title: string;
    }) => {
      await apiClient.threads.updateState(threadId, {
        values: { title },
      });
    },
    onSuccess(_, { threadId, title }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread>) => {
          return oldData.map((t) => {
            if (t.thread_id === threadId) {
              return {
                ...t,
                values: {
                  ...t.values,
                  title,
                },
              };
            }
            return t;
          });
        },
      );
    },
  });
}
