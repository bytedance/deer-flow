import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

import { getAPIClient } from "../api";
import { getBackendBaseURL } from "../config";
import { useI18n } from "../i18n/hooks";
import {
  extractTextFromMessage,
  getMessagesUpToTurn,
  hasContent,
  isRegeneratableMessage,
  resolveTurnForMessage,
  type FileInMessage,
} from "../messages/utils";
import type { LocalSettings } from "../settings";
import { useUpdateSubtask } from "../tasks/context";
import type { UploadedFileInfo } from "../uploads";
import { promptInputFilePartToFile, uploadFiles } from "../uploads";

import type { AgentThread, AgentThreadState } from "./types";
import {
  applyHumanEdit,
  appendAssistantVersion,
  buildSubmissionMessages,
  selectAssistantVersion,
} from "./versioning";

export type ToolEndEvent = {
  name: string;
  data: unknown;
};

export type ThreadStreamOptions = {
  threadId?: string | null | undefined;
  context: LocalSettings["context"];
  isMock?: boolean;
  onStart?: (threadId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
};

type SendMessageOptions = {
  additionalKwargs?: Record<string, unknown>;
};

function normalizeStoredRunId(runId: string | null): string | null {
  if (!runId) {
    return null;
  }

  const trimmed = runId.trim();
  if (!trimmed) {
    return null;
  }

  const queryIndex = trimmed.indexOf("?");
  if (queryIndex >= 0) {
    const params = new URLSearchParams(trimmed.slice(queryIndex + 1));
    const queryRunId = params.get("run_id")?.trim();
    if (queryRunId) {
      return queryRunId;
    }
  }

  const pathWithoutQueryOrHash = trimmed.split(/[?#]/, 1)[0]?.trim() ?? "";
  if (!pathWithoutQueryOrHash) {
    return null;
  }

  const runsMarker = "/runs/";
  const runsIndex = pathWithoutQueryOrHash.lastIndexOf(runsMarker);
  if (runsIndex >= 0) {
    const runIdAfterMarker = pathWithoutQueryOrHash
      .slice(runsIndex + runsMarker.length)
      .split("/", 1)[0]
      ?.trim();
    if (runIdAfterMarker) {
      return runIdAfterMarker;
    }
    return null;
  }

  const segments = pathWithoutQueryOrHash
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean);
  return segments.at(-1) ?? null;
}

function getRunMetadataStorage(): {
  getItem(key: `lg:stream:${string}`): string | null;
  setItem(key: `lg:stream:${string}`, value: string): void;
  removeItem(key: `lg:stream:${string}`): void;
} {
  return {
    getItem(key) {
      const normalized = normalizeStoredRunId(
        window.sessionStorage.getItem(key),
      );
      if (normalized) {
        window.sessionStorage.setItem(key, normalized);
        return normalized;
      }
      window.sessionStorage.removeItem(key);
      return null;
    },
    setItem(key, value) {
      const normalized = normalizeStoredRunId(value);
      if (normalized) {
        window.sessionStorage.setItem(key, normalized);
        return;
      }
      window.sessionStorage.removeItem(key);
    },
    removeItem(key) {
      window.sessionStorage.removeItem(key);
    },
  };
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

function resolveReasoningEffort(context: LocalSettings["context"]) {
  return (
    context.reasoning_effort ??
    (context.mode === "ultra"
      ? "high"
      : context.mode === "pro"
        ? "medium"
        : context.mode === "thinking"
          ? "low"
          : undefined)
  );
}

function buildRunContext(
  context: LocalSettings["context"],
  options?: {
    threadId?: string;
    extraContext?: Record<string, unknown>;
  },
) {
  const nextContext = {
    ...options?.extraContext,
    ...context,
    thinking_enabled: context.mode !== "flash",
    is_plan_mode: context.mode === "pro" || context.mode === "ultra",
    subagent_enabled: context.mode === "ultra",
    reasoning_effort: resolveReasoningEffort(context),
  };

  if (!options?.threadId) {
    return nextContext;
  }

  return {
    ...nextContext,
    thread_id: options.threadId,
  };
}

function extractLatestAssistantText(messages: Message[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || message.type !== "ai") {
      continue;
    }
    if (!hasContent(message) || message.tool_calls?.length) {
      continue;
    }
    const text = extractTextFromMessage(message).trim();
    if (text) {
      return text;
    }
  }
  return null;
}

export function useThreadStream({
  threadId,
  context,
  isMock,
  onStart,
  onFinish,
  onToolEnd,
}: ThreadStreamOptions) {
  const { t } = useI18n();
  const apiClient = getAPIClient(isMock);
  // Track the thread ID that is currently streaming to handle thread changes during streaming
  const [onStreamThreadId, setOnStreamThreadId] = useState(() => threadId);
  const [localStateOverride, setLocalStateOverride] = useState<AgentThreadState | null>(null);
  // Ref to track current thread ID across async callbacks without causing re-renders,
  // and to allow access to the current thread id in onUpdateEvent
  const threadIdRef = useRef<string | null>(threadId ?? null);
  const startedRef = useRef(false);
  const effectiveStateRef = useRef<AgentThreadState | null>(null);

  const listeners = useRef({
    onStart,
    onFinish,
    onToolEnd,
  });

  // Keep listeners ref updated with latest callbacks
  useEffect(() => {
    listeners.current = { onStart, onFinish, onToolEnd };
  }, [onStart, onFinish, onToolEnd]);

  useEffect(() => {
    const normalizedThreadId = threadId ?? null;
    if (!normalizedThreadId) {
      // Just reset for new thread creation when threadId becomes null/undefined
      startedRef.current = false;
      setOnStreamThreadId(normalizedThreadId);
    }
    threadIdRef.current = normalizedThreadId;
    setLocalStateOverride(null);
  }, [threadId]);

  const _handleOnStart = useCallback((id: string) => {
    if (!startedRef.current) {
      listeners.current.onStart?.(id);
      startedRef.current = true;
    }
  }, []);

  const handleStreamStart = useCallback(
    (_threadId: string) => {
      threadIdRef.current = _threadId;
      _handleOnStart(_threadId);
    },
    [_handleOnStart],
  );

  const queryClient = useQueryClient();
  const updateSubtask = useUpdateSubtask();
  const runMetadataStorageRef = useRef<
    ReturnType<typeof getRunMetadataStorage> | undefined
  >(undefined);

  if (
    typeof window !== "undefined" &&
    runMetadataStorageRef.current === undefined
  ) {
    runMetadataStorageRef.current = getRunMetadataStorage();
  }

  const thread = useStream<AgentThreadState>({
    client: apiClient,
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    reconnectOnMount: runMetadataStorageRef.current
      ? () => runMetadataStorageRef.current!
      : false,
    fetchStateHistory: { limit: 1 },
    onCreated(meta) {
      handleStreamStart(meta.thread_id);
      setOnStreamThreadId(meta.thread_id);
    },
    onLangChainEvent(event) {
      if (event.event === "on_tool_end") {
        listeners.current.onToolEnd?.({
          name: event.name,
          data: event.data,
        });
      }
    },
    onUpdateEvent(data) {
      const updates: Array<Partial<AgentThreadState> | null> = Object.values(
        data || {},
      );
      for (const update of updates) {
        if (update && "title" in update && update.title) {
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
    onCustomEvent(event: unknown) {
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
    onError(error) {
      setOptimisticMessages([]);
      toast.error(getStreamErrorMessage(error));
    },
    onFinish(state) {
      setLocalStateOverride(state.values);
      listeners.current.onFinish?.(state.values);
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });

  const effectiveState = localStateOverride ?? thread.values;
  const effectiveMessages = localStateOverride
    ? thread.isLoading
      ? [
          ...localStateOverride.messages,
          ...thread.messages.slice(localStateOverride.messages.length),
        ]
      : localStateOverride.messages
    : thread.messages;

  useEffect(() => {
    effectiveStateRef.current = effectiveState;
  }, [effectiveState]);

  const updateThreadSearchCache = useCallback(
    (targetThreadId: string, nextState: AgentThreadState) => {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          return oldData?.map((candidate) => {
            if (candidate.thread_id !== targetThreadId) {
              return candidate;
            }
            return {
              ...candidate,
              values: nextState,
            };
          });
        },
      );
    },
    [queryClient],
  );

  const getCurrentThreadState = useCallback(
    async (targetThreadId: string) => {
      const currentState = effectiveStateRef.current;
      if (
        threadIdRef.current === targetThreadId &&
        currentState &&
        Array.isArray(currentState.messages)
      ) {
        return currentState;
      }

      const state = await apiClient.threads.getState<AgentThreadState>(targetThreadId);
      return state.values;
    },
    [apiClient],
  );

  const persistThreadState = useCallback(
    async (targetThreadId: string, nextState: AgentThreadState) => {
      const previousState = effectiveStateRef.current;
      setLocalStateOverride(nextState);
      try {
        await apiClient.threads.updateState(targetThreadId, {
          values: nextState,
        });
        updateThreadSearchCache(targetThreadId, nextState);
      } catch (error) {
        setLocalStateOverride(previousState);
        throw error;
      }
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
    [apiClient, queryClient, updateThreadSearchCache],
  );

  const editHumanMessage = useCallback(
    async (targetThreadId: string, messageId: string, text: string) => {
      const nextText = text.trim();
      if (!nextText || thread.isLoading) {
        return;
      }

      try {
        const currentState = await getCurrentThreadState(targetThreadId);
        const currentMessage = currentState.messages.find(
          (message) => message.id === messageId,
        );
        if (!currentMessage || currentMessage.type !== "human") {
          return;
        }
        if (extractTextFromMessage(currentMessage).trim() === nextText) {
          return;
        }

        const nextState = applyHumanEdit(currentState, {
          messageId,
          text: nextText,
        });
        await persistThreadState(targetThreadId, nextState);
      } catch (error) {
        toast.error(getStreamErrorMessage(error));
        throw error;
      }
    },
    [getCurrentThreadState, persistThreadState, thread.isLoading],
  );

  const setAssistantVersion = useCallback(
    async (targetThreadId: string, messageId: string, versionId: string) => {
      if (thread.isLoading) {
        return;
      }

      try {
        const currentState = await getCurrentThreadState(targetThreadId);
        const activeVersionId = currentState.active_version_map?.[messageId];
        if (activeVersionId === versionId) {
          return;
        }
        const nextState = selectAssistantVersion(currentState, {
          messageId,
          versionId,
        });
        await persistThreadState(targetThreadId, nextState);
      } catch (error) {
        toast.error(getStreamErrorMessage(error));
        throw error;
      }
    },
    [getCurrentThreadState, persistThreadState, thread.isLoading],
  );

  const regenerateTurn = useCallback(
    async (targetThreadId: string, messageId: string) => {
      if (thread.isLoading) {
        return;
      }

      try {
        const currentState = await getCurrentThreadState(targetThreadId);
        const visibleMessages = buildSubmissionMessages(currentState);
        if (!isRegeneratableMessage(visibleMessages, messageId)) {
          return;
        }

        const turn = resolveTurnForMessage(visibleMessages, messageId);
        if (!turn?.assistantMessageId) {
          return;
        }

        const inputMessages = getMessagesUpToTurn(visibleMessages, turn.turnId, {
          includeAssistant: false,
        });
        const regeneratedValues = (await apiClient.runs.wait(null, "lead_agent", {
          input: {
            messages: inputMessages,
          },
          context: buildRunContext(context),
          config: {
            recursion_limit: 1000,
          },
        })) as AgentThreadState;

        const regeneratedText = extractLatestAssistantText(
          regeneratedValues.messages ?? [],
        );
        if (!regeneratedText) {
          throw new Error("Failed to regenerate assistant response.");
        }

        const nextState = appendAssistantVersion(currentState, {
          turnId: turn.turnId,
          messageId: turn.assistantMessageId,
          text: regeneratedText,
          contextSnapshot: {
            model_name:
              typeof context.model_name === "string"
                ? context.model_name
                : undefined,
            mode: typeof context.mode === "string" ? context.mode : undefined,
            reasoning_effort: resolveReasoningEffort(context),
          },
        });
        await persistThreadState(targetThreadId, nextState);
      } catch (error) {
        toast.error(getStreamErrorMessage(error));
        throw error;
      }
    },
    [apiClient, context, getCurrentThreadState, persistThreadState, thread.isLoading],
  );

  // Optimistic messages shown before the server stream responds
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const sendInFlightRef = useRef(false);
  // Track message count before sending so we know when server has responded
  const prevMsgCountRef = useRef(effectiveMessages.length);

  // Clear optimistic when server messages arrive (count increases)
  useEffect(() => {
    if (
      optimisticMessages.length > 0 &&
      effectiveMessages.length > prevMsgCountRef.current
    ) {
      setOptimisticMessages([]);
    }
  }, [effectiveMessages.length, optimisticMessages.length]);

  const sendMessage = useCallback(
    async (
      targetThreadId: string,
      message: PromptInputMessage,
      extraContext?: Record<string, unknown>,
      options?: SendMessageOptions,
    ) => {
      if (sendInFlightRef.current) {
        return;
      }
      sendInFlightRef.current = true;

      const text = message.text.trim();

      // Capture current count before showing optimistic messages
      prevMsgCountRef.current = effectiveMessages.length;

      // Build optimistic files list with uploading status
      const optimisticFiles: FileInMessage[] = (message.files ?? []).map(
        (f) => ({
          filename: f.filename ?? "",
          size: 0,
          status: "uploading" as const,
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

      _handleOnStart(targetThreadId);

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

            if (!targetThreadId) {
              throw new Error("Thread is not ready for file upload.");
            }

            if (files.length > 0) {
              const uploadResponse = await uploadFiles(targetThreadId, files);
              uploadedFileInfo = uploadResponse.files;

              // Update optimistic human message with uploaded status + paths
              const uploadedFiles: FileInMessage[] = uploadedFileInfo.map(
                (info) => ({
                  filename: info.filename,
                  size: info.size,
                  path: info.virtual_path,
                  status: "uploaded" as const,
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
            status: "uploaded" as const,
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
                    text,
                  },
                ],
                additional_kwargs: {
                  ...options?.additionalKwargs,
                  ...(filesForSubmit.length > 0
                    ? { files: filesForSubmit }
                    : {}),
                },
              },
            ],
          },
          {
            threadId: targetThreadId,
            streamSubgraphs: true,
            streamResumable: true,
            config: {
              recursion_limit: 1000,
            },
            context: buildRunContext(context, {
              threadId: targetThreadId,
              extraContext,
            }),
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
    [thread, _handleOnStart, t.uploads.uploadingFiles, context, queryClient, effectiveMessages.length],
  );

  const displayThread = {
    ...thread,
    values: effectiveState,
    messages: effectiveMessages,
  } as typeof thread;

  // Merge thread with optimistic messages for display
  const mergedThread =
    optimisticMessages.length > 0
      ? ({
          ...displayThread,
          messages: [...displayThread.messages, ...optimisticMessages],
        } as typeof thread)
      : displayThread;

  return [
    mergedThread,
    sendMessage,
    isUploading,
    {
      editHumanMessage,
      regenerateTurn,
      selectAssistantVersion: setAssistantVersion,
      stopThread: thread.stop,
      isThreadStreaming: thread.isLoading,
    },
  ] as const;
}

export function useThreads(
  params: Parameters<ThreadsClient["search"]>[0] = {
    limit: 50,
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values"],
  },
) {
  const apiClient = getAPIClient();
  return useQuery<AgentThread[]>({
    queryKey: ["threads", "search", params],
    queryFn: async () => {
      const maxResults = params.limit;
      const initialOffset = params.offset ?? 0;
      const DEFAULT_PAGE_SIZE = 50;

      // Preserve prior semantics: if a non-positive limit is explicitly provided,
      // delegate to a single search call with the original parameters.
      if (maxResults !== undefined && maxResults <= 0) {
        const response =
          await apiClient.threads.search<AgentThreadState>(params);
        return response as AgentThread[];
      }

      const pageSize =
        typeof maxResults === "number" && maxResults > 0
          ? Math.min(DEFAULT_PAGE_SIZE, maxResults)
          : DEFAULT_PAGE_SIZE;

      const threads: AgentThread[] = [];
      let offset = initialOffset;

      while (true) {
        if (typeof maxResults === "number" && threads.length >= maxResults) {
          break;
        }

        const currentLimit =
          typeof maxResults === "number"
            ? Math.min(pageSize, maxResults - threads.length)
            : pageSize;

        if (typeof maxResults === "number" && currentLimit <= 0) {
          break;
        }

        const response = (await apiClient.threads.search<AgentThreadState>({
          ...params,
          limit: currentLimit,
          offset,
        })) as AgentThread[];

        threads.push(...response);

        if (response.length < currentLimit) {
          break;
        }

        offset += response.length;
      }

      return threads;
    },
    refetchOnWindowFocus: false,
  });
}

export function useDeleteThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  return useMutation({
    mutationFn: async ({ threadId }: { threadId: string }) => {
      await apiClient.threads.delete(threadId);

      const response = await fetch(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
        {
          method: "DELETE",
        },
      );

      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Failed to delete local thread data." }));
        throw new Error(error.detail ?? "Failed to delete local thread data.");
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
