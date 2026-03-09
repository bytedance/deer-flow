import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

import { getAPIClient } from "../api";
import { getBackendBaseURL } from "../config";
import { useI18n } from "../i18n/hooks";
import type { FileInMessage } from "../messages/utils";
import type { LocalSettings } from "../settings";
import { useUpdateSubtask } from "../tasks/context";
import type { UploadedFileInfo } from "../uploads";
import { uploadFiles } from "../uploads";

import type { AgentThreadState, ThreadListItem } from "./types";

const THREADS_LIST_QUERY_KEY = ["threads", "search"] as const;

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

export function useThreadStream({
  threadId,
  context,
  isMock,
  onStart,
  onFinish,
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
    onToolEnd,
  });

  // Keep listeners ref updated with latest callbacks
  useEffect(() => {
    listeners.current = { onStart, onFinish, onToolEnd };
  }, [onStart, onFinish, onToolEnd]);

  useEffect(() => {
    const normalizedThreadId = threadId ?? null;
    if (threadIdRef.current !== normalizedThreadId) {
      threadIdRef.current = normalizedThreadId;
      startedRef.current = false; // Reset for new thread
      setOnStreamThreadId(normalizedThreadId);
    }
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
      setOnStreamThreadId(_threadId);
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
              queryKey: THREADS_LIST_QUERY_KEY,
              exact: false,
            },
            (oldData: Array<ThreadListItem> | undefined) => {
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
    onFinish(state) {
      listeners.current.onFinish?.(state.values);
      void queryClient.invalidateQueries({ queryKey: THREADS_LIST_QUERY_KEY });
    },
  });

  // Optimistic messages shown before the server stream responds
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
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
            streamMode: ["values", "messages-tuple", "custom"],
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
        void queryClient.invalidateQueries({ queryKey: THREADS_LIST_QUERY_KEY });
      } catch (error) {
        setOptimisticMessages([]);
        throw error;
      }
    },
    [thread, _handleOnStart, t.uploads.uploadingFiles, context, queryClient],
  );

  // Merge thread with optimistic messages for display
  const mergedThread =
    optimisticMessages.length > 0
      ? ({
          ...thread,
          messages: [...thread.messages, ...optimisticMessages],
        } as typeof thread)
      : thread;

  return [mergedThread, sendMessage] as const;
}


type ThreadSummaryApiResponse = {
  threads: ThreadListItem[];
  next_offset: number | null;
};

type ThreadListQueryParams = {
  limit?: number;
  offset?: number;
  sortBy?: "updated_at" | "created_at";
  sortOrder?: "asc" | "desc";
};

async function fetchThreadSummariesPage(
  params: Required<ThreadListQueryParams>,
): Promise<ThreadSummaryApiResponse> {
  const baseURL = getBackendBaseURL();
  const url = new URL(`${baseURL}/api/threads/summaries`,
    typeof window !== "undefined" ? window.location.origin : "http://localhost:2026",
  );
  url.searchParams.set("limit", String(params.limit));
  url.searchParams.set("offset", String(params.offset));
  url.searchParams.set("sort_by", params.sortBy);
  url.searchParams.set("sort_order", params.sortOrder);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`Failed to fetch thread summaries: ${response.status}`);
  }
  return (await response.json()) as ThreadSummaryApiResponse;
}

export function useThreads(
  params: ThreadListQueryParams = {
    limit: 50,
    sortBy: "updated_at",
    sortOrder: "desc",
  },
) {
  const pageSize = params.limit ?? 50;
  const initialOffset = params.offset ?? 0;
  const sortBy = params.sortBy ?? "updated_at";
  const sortOrder = params.sortOrder ?? "desc";

  return useQuery<ThreadListItem[]>({
    queryKey: [...THREADS_LIST_QUERY_KEY, pageSize, initialOffset, sortBy, sortOrder],
    queryFn: async () => {
      const allThreads: ThreadListItem[] = [];
      let offset = initialOffset;
      const seenOffsets = new Set<number>();

      while (true) {
        if (seenOffsets.has(offset)) {
          throw new Error(`Detected repeated thread summaries offset: ${offset}`);
        }
        seenOffsets.add(offset);

        const page = await fetchThreadSummariesPage({
          limit: pageSize,
          offset,
          sortBy,
          sortOrder,
        });

        if (!Array.isArray(page.threads) || page.threads.length === 0) {
          break;
        }

        allThreads.push(...page.threads);

        if (page.next_offset == null) {
          break;
        }

        if (page.next_offset <= offset) {
          throw new Error(
            `Thread summaries pagination did not advance: ${page.next_offset}`,
          );
        }

        offset = page.next_offset;
      }

      return allThreads;
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
          queryKey: THREADS_LIST_QUERY_KEY,
          exact: false,
        },
        (oldData: Array<ThreadListItem> | undefined) => {
          return oldData?.filter((t) => t.thread_id !== threadId) ?? oldData;
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
          queryKey: THREADS_LIST_QUERY_KEY,
          exact: false,
        },
        (oldData: Array<ThreadListItem> | undefined) => {
          return oldData?.map((t) => {
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
          }) ?? oldData;
        },
      );
    },
  });
}
