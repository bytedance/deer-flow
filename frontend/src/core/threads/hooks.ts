import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

import { getAPIClient } from "../api";
import { useI18n } from "../i18n/hooks";
import type { FileInMessage } from "../messages/utils";
import type { LocalSettings } from "../settings";
import { useUpdateSubtask } from "../tasks/context";
import type { UploadedFileInfo } from "../uploads";
import { uploadFiles } from "../uploads";

import type { AgentThread, AgentThreadState } from "./types";

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
  onThreadUpdate?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
};

const BACKGROUND_THREAD_SYNC_MS = 5000;
const EMPTY_MESSAGES: Message[] = [];
const EMPTY_ARTIFACTS: string[] = [];

function shouldSyncInBackground() {
  if (typeof document === "undefined") {
    return false;
  }
  return document.hidden || !document.hasFocus();
}

function messageIdOf(message: Message) {
  return typeof message.id === "string" && message.id.length > 0
    ? message.id
    : null;
}

function hasSameLastMessage(previous: Message[], next: Message[]) {
  if (previous.length === 0 && next.length === 0) {
    return true;
  }

  const previousLast = previous.at(-1);
  const nextLast = next.at(-1);
  if (!previousLast || !nextLast) {
    return false;
  }

  const previousId = messageIdOf(previousLast);
  const nextId = messageIdOf(nextLast);
  if (previousId && nextId) {
    return previousId === nextId;
  }

  return JSON.stringify(previousLast.content) === JSON.stringify(nextLast.content);
}

function getNewMessages(previous: Message[], next: Message[]) {
  const previousIds = new Set(
    previous
      .map((message) => messageIdOf(message))
      .filter((id): id is string => id !== null),
  );

  const unseenById = next.filter((message) => {
    const id = messageIdOf(message);
    return id ? !previousIds.has(id) : false;
  });
  if (unseenById.length > 0) {
    return unseenById;
  }

  if (next.length > previous.length) {
    return next.slice(previous.length);
  }

  return [];
}

function shouldReplaceThreadState(
  current: AgentThreadState | null,
  next: AgentThreadState,
) {
  if (current === null) {
    return true;
  }

  if (current.messages.length !== next.messages.length) {
    return true;
  }
  if (!hasSameLastMessage(current.messages, next.messages)) {
    return true;
  }
  if (current.title !== next.title) {
    return true;
  }
  if (current.artifacts.length !== next.artifacts.length) {
    return true;
  }
  if ((current.todos?.length ?? 0) !== (next.todos?.length ?? 0)) {
    return true;
  }

  return false;
}

function pickLatestThreadState(
  streamValues: AgentThreadState,
  syncedValues: AgentThreadState | null,
) {
  if (syncedValues === null) {
    return streamValues;
  }

  if (syncedValues.messages.length > streamValues.messages.length) {
    return syncedValues;
  }
  if (syncedValues.messages.length < streamValues.messages.length) {
    return streamValues;
  }
  if (!hasSameLastMessage(streamValues.messages, syncedValues.messages)) {
    return syncedValues;
  }
  if (syncedValues.artifacts.length > streamValues.artifacts.length) {
    return syncedValues;
  }
  if ((syncedValues.todos?.length ?? 0) > (streamValues.todos?.length ?? 0)) {
    return syncedValues;
  }
  if (syncedValues.title && syncedValues.title !== streamValues.title) {
    return syncedValues;
  }

  return streamValues;
}

function normalizeThreadState(
  values: Partial<AgentThreadState> | null | undefined,
  fallbackMessages: Message[] = EMPTY_MESSAGES,
): AgentThreadState {
  const title = typeof values?.title === "string" ? values.title : "";
  const messages = Array.isArray(values?.messages)
    ? values.messages
    : fallbackMessages;
  const artifacts = Array.isArray(values?.artifacts)
    ? values.artifacts
    : EMPTY_ARTIFACTS;
  const todos = Array.isArray(values?.todos) ? values.todos : undefined;

  if (
    values?.title === title &&
    values?.messages === messages &&
    values?.artifacts === artifacts &&
    values?.todos === todos
  ) {
    return values as AgentThreadState;
  }

  return {
    title,
    messages,
    artifacts,
    todos,
  };
}

function shouldOverrideThreadValues(
  current: AgentThreadState,
  next: AgentThreadState,
) {
  return (
    current.title !== next.title ||
    current.messages !== next.messages ||
    current.artifacts !== next.artifacts ||
    current.todos !== next.todos
  );
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

export function useThreadStream({
  threadId,
  context,
  isMock,
  onStart,
  onFinish,
  onThreadUpdate,
  onToolEnd,
}: ThreadStreamOptions) {
  const { t } = useI18n();
  // Track the thread ID that is currently streaming to handle thread changes during streaming
  const [onStreamThreadId, setOnStreamThreadId] = useState(() => threadId);
  // Ref to track current thread ID across async callbacks without causing re-renders,
  // and to allow access to the current thread id in onUpdateEvent
  const threadIdRef = useRef<string | null>(threadId ?? null);
  const startedRef = useRef(false);

  const listeners = useRef({
    onStart,
    onFinish,
    onThreadUpdate,
    onToolEnd,
  });

  // Keep listeners ref updated with latest callbacks
  useEffect(() => {
    listeners.current = { onStart, onFinish, onThreadUpdate, onToolEnd };
  }, [onFinish, onStart, onThreadUpdate, onToolEnd]);

  useEffect(() => {
    const normalizedThreadId = threadId ?? null;
    if (!normalizedThreadId) {
      // Just reset for new thread creation when threadId becomes null/undefined
      startedRef.current = false;
      setOnStreamThreadId(normalizedThreadId);
    }
    threadIdRef.current = normalizedThreadId;
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

  const thread = useStream<AgentThreadState>({
    client: getAPIClient(isMock),
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    reconnectOnMount: true,
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
      }
    },
    onError(error) {
      setOptimisticMessages([]);
      toast.error(getStreamErrorMessage(error));
    },
    onFinish(state) {
      listeners.current.onFinish?.(state.values);
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });

  const [syncedThreadState, setSyncedThreadState] =
    useState<AgentThreadState | null>(null);
  const syncedThreadStateRef = useRef<AgentThreadState | null>(null);
  const streamStateRef = useRef({
    messages: thread.messages,
    values: normalizeThreadState(thread.values, thread.messages),
    isLoading: thread.isLoading,
  });
  const backgroundSyncReadyRef = useRef(false);
  const [shouldBackgroundSync, setShouldBackgroundSync] = useState(() =>
    shouldSyncInBackground(),
  );

  useEffect(() => {
    streamStateRef.current = {
      messages: thread.messages,
      values: normalizeThreadState(thread.values, thread.messages),
      isLoading: thread.isLoading,
    };
  }, [thread.isLoading, thread.messages, thread.values]);

  useEffect(() => {
    syncedThreadStateRef.current = syncedThreadState;
  }, [syncedThreadState]);

  useEffect(() => {
    setSyncedThreadState(null);
    syncedThreadStateRef.current = null;
    backgroundSyncReadyRef.current = false;
  }, [onStreamThreadId]);

  useEffect(() => {
    const updateBackgroundSyncState = () => {
      setShouldBackgroundSync(shouldSyncInBackground());
    };

    updateBackgroundSyncState();
    document.addEventListener("visibilitychange", updateBackgroundSyncState);
    window.addEventListener("focus", updateBackgroundSyncState);
    window.addEventListener("blur", updateBackgroundSyncState);

    return () => {
      document.removeEventListener(
        "visibilitychange",
        updateBackgroundSyncState,
      );
      window.removeEventListener("focus", updateBackgroundSyncState);
      window.removeEventListener("blur", updateBackgroundSyncState);
    };
  }, []);

  useEffect(() => {
    if (
      !onStreamThreadId ||
      !onThreadUpdate ||
      !shouldBackgroundSync ||
      thread.isLoading
    ) {
      return;
    }

    const client = getAPIClient(isMock);
    let disposed = false;
    let inFlight = false;

    const syncThreadState = async () => {
      if (disposed || inFlight) {
        return;
      }

      inFlight = true;
      try {
        const latest = await client.threads.getState<AgentThreadState>(
          onStreamThreadId,
        );
        if (disposed) {
          return;
        }

        const nextValues = normalizeThreadState(latest.values);
        const currentStreamState = streamStateRef.current;
        const currentMergedState = pickLatestThreadState(
          currentStreamState.values,
          syncedThreadStateRef.current,
        );
        const newMessages = getNewMessages(
          currentMergedState.messages,
          nextValues.messages,
        );

        if (shouldReplaceThreadState(syncedThreadStateRef.current, nextValues)) {
          setSyncedThreadState(nextValues);
          syncedThreadStateRef.current = nextValues;
          void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
        }

        if (!backgroundSyncReadyRef.current) {
          backgroundSyncReadyRef.current = true;
          return;
        }

        if (
          !currentStreamState.isLoading &&
          newMessages.some((message) => message.type === "ai")
        ) {
          listeners.current.onThreadUpdate?.(nextValues);
        }
      } catch (error) {
        console.warn("Failed to sync thread state", error);
      } finally {
        inFlight = false;
      }
    };

    void syncThreadState();
    const intervalId = window.setInterval(() => {
      void syncThreadState();
    }, BACKGROUND_THREAD_SYNC_MS);

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
    };
  }, [
    isMock,
    onStreamThreadId,
    onThreadUpdate,
    queryClient,
    shouldBackgroundSync,
    thread.isLoading,
  ]);

  // Optimistic messages shown before the server stream responds
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const sendInFlightRef = useRef(false);
  // Track message count before sending so we know when server has responded
  const prevMsgCountRef = useRef(thread.messages.length);

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
    ) => {
      if (sendInFlightRef.current) {
        return;
      }
      sendInFlightRef.current = true;

      const text = message.text.trim();

      // Capture current count before showing optimistic messages
      prevMsgCountRef.current = thread.messages.length;

      // Build optimistic files list with uploading status
      const optimisticFiles: FileInMessage[] = (message.files ?? []).map(
        (f) => ({
          filename: f.filename ?? "",
          size: 0,
          status: "uploading" as const,
        }),
      );

      // Create optimistic human message (shown immediately)
      const optimisticHumanMsg: Message = {
        type: "human",
        id: `opt-human-${Date.now()}`,
        content: text ? [{ type: "text", text }] : "",
        additional_kwargs:
          optimisticFiles.length > 0 ? { files: optimisticFiles } : {},
      };

      const newOptimistic: Message[] = [optimisticHumanMsg];
      if (optimisticFiles.length > 0) {
        // Mock AI message while files are being uploaded
        newOptimistic.push({
          type: "ai",
          id: `opt-ai-${Date.now()}`,
          content: t.uploads.uploadingFiles,
          additional_kwargs: { element: "task" },
        });
      }
      setOptimisticMessages(newOptimistic);

      _handleOnStart(threadId);

      let uploadedFileInfo: UploadedFileInfo[] = [];

      try {
        // Upload files first if any
        if (message.files && message.files.length > 0) {
          setIsUploading(true);
          try {
            // Convert FileUIPart to File objects by fetching blob URLs
            const filePromises = message.files.map(async (fileUIPart) => {
              if (fileUIPart.url && fileUIPart.filename) {
                try {
                  // Fetch the blob URL to get the file data
                  const response = await fetch(fileUIPart.url);
                  const blob = await response.blob();

                  // Create a File object from the blob
                  return new File([blob], fileUIPart.filename, {
                    type: fileUIPart.mediaType || blob.type,
                  });
                } catch (error) {
                  console.error(
                    `Failed to fetch file ${fileUIPart.filename}:`,
                    error,
                  );
                  return null;
                }
              }
              return null;
            });

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
            console.error("Failed to upload files:", error);
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
                additional_kwargs:
                  filesForSubmit.length > 0 ? { files: filesForSubmit } : {},
              },
            ],
          },
          {
            threadId: threadId,
            streamSubgraphs: true,
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
              thread_id: threadId,
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
    [thread, _handleOnStart, t.uploads.uploadingFiles, context, queryClient],
  );

  // Only wrap the SDK thread when the displayed values/messages differ from
  // the stream snapshot. This avoids extra object churn when no override is
  // needed while still letting background sync and optimistic UI win.
  const normalizedThreadValues = normalizeThreadState(
    thread.values,
    thread.messages,
  );
  const latestThreadValues = pickLatestThreadState(
    normalizedThreadValues,
    syncedThreadState,
  );
  const mergedMessages =
    optimisticMessages.length > 0
      ? [...latestThreadValues.messages, ...optimisticMessages]
      : latestThreadValues.messages;

  const shouldOverrideValues = shouldOverrideThreadValues(
    thread.values,
    latestThreadValues,
  );
  const shouldOverrideMessages = thread.messages !== mergedMessages;
  const mergedThread =
    shouldOverrideValues || shouldOverrideMessages
      ? ({
          ...thread,
          values: latestThreadValues,
          messages: mergedMessages,
        } as typeof thread)
      : thread;

  return [mergedThread, sendMessage, isUploading] as const;
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
        const response = await apiClient.threads.search<AgentThreadState>(params);
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
    },
    onSuccess(_, { threadId }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread>) => {
          return oldData.filter((t) => t.thread_id !== threadId);
        },
      );
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
