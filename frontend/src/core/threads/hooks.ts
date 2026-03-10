import type { HumanMessage } from "@langchain/core/messages";
import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import { useStream, type UseStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

import { getAPIClient } from "../api";
import { authFetch } from "../auth/fetch";
import { useUpdateSubtask } from "../tasks/context";
import { uploadFiles } from "../uploads";

import type {
  AgentThread,
  AgentThreadContext,
  AgentThreadState,
} from "./types";
import {
  resetTurnUsage,
  setTurnUsageThread,
  startTurnUsage,
  updateTurnUsage,
} from "./usage-context";

export interface ThreadResubmitOptions {
  checkpoint?: {
    checkpoint_id: string | null;
    checkpoint_ns: string;
    checkpoint_map: Record<string, unknown>;
  } | null;
  streamResumable?: boolean;
}

export function useThreadStream({
  threadId,
  isNewThread,
  onFinish,
}: {
  isNewThread: boolean;
  threadId: string | null | undefined;
  onFinish?: (state: AgentThreadState) => void;
}) {
  const queryClient = useQueryClient();
  const updateSubtask = useUpdateSubtask();
  useEffect(() => {
    if (threadId) {
      setTurnUsageThread(threadId, { restore: !isNewThread });
    }
  }, [threadId, isNewThread]);
  const thread = useStream<AgentThreadState>({
    client: getAPIClient(),
    assistantId: "lead_agent",
    threadId: isNewThread ? undefined : threadId,
    reconnectOnMount: true,
    fetchStateHistory: { limit: 1 },
    onCustomEvent(event: unknown) {
      console.info(event);
      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event
      ) {
        const eventType = (event as { type: string }).type;

        if (eventType === "task_started") {
          const e = event as {
            type: "task_started";
            task_id: string;
            description: string;
            subagent_type?: string;
            prompt?: string;
          };
          updateSubtask({
            id: e.task_id,
            status: "in_progress",
            description: e.description ?? "",
            subagent_type: e.subagent_type ?? "agent",
            prompt: e.prompt ?? "",
            createdAt: Date.now(),
            messageIndex: 0,
            totalMessages: 0,
            messageHistory: [],
          });
        } else if (eventType === "task_running") {
          const e = event as {
            type: "task_running";
            task_id: string;
            message: Message;
            message_index?: number;
            total_messages?: number;
          };
          // Only update latestMessage for AI messages (used by card status display).
          // All messages (AI + tool) go into trajectory via _trajectoryMessage.
          const isAiMessage = e.message?.type === "ai";
          updateSubtask({
            id: e.task_id,
            latestMessage: isAiMessage ? (e.message as AIMessage) : undefined,
            messageIndex: e.message_index ?? 0,
            totalMessages: e.total_messages ?? 0,
            _trajectoryMessage: e.message,
          });
        } else if (eventType === "task_completed") {
          const e = event as {
            type: "task_completed";
            task_id: string;
            result?: string;
            trajectory?: Message[];
          };
          updateSubtask({
            id: e.task_id,
            status: "completed",
            result: e.result,
            // Replace messageHistory with the complete trajectory if provided
            ...(e.trajectory && e.trajectory.length > 0
              ? { messageHistory: e.trajectory }
              : {}),
          });
        } else if (eventType === "task_failed") {
          const e = event as {
            type: "task_failed";
            task_id: string;
            error?: string;
            trajectory?: Message[];
          };
          updateSubtask({
            id: e.task_id,
            status: "failed",
            error: e.error ?? "Task failed",
            ...(e.trajectory && e.trajectory.length > 0
              ? { messageHistory: e.trajectory }
              : {}),
          });
        } else if (eventType === "task_timed_out") {
          const e = event as {
            type: "task_timed_out";
            task_id: string;
            error?: string;
          };
          updateSubtask({
            id: e.task_id,
            status: "failed",
            error: e.error ?? "Task timed out",
          });
        } else if (eventType === "usage_update") {
          const e = event as {
            type: "usage_update";
            input_tokens: number;
            output_tokens: number;
          };
          updateTurnUsage({
            input_tokens: e.input_tokens,
            output_tokens: e.output_tokens,
          });
        }
      }
    },
    onFinish(state) {
      onFinish?.(state.values);
      // void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
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
                  title: state.values.title,
                },
              };
            }
            return t;
          });
        },
      );
    },
  });

  return thread;
}

export function useSubmitThread({
  threadId,
  thread,
  threadContext,
  isNewThread,
  afterSubmit,
  onUploadStart,
  onUploadEnd,
}: {
  isNewThread: boolean;
  threadId: string | null | undefined;
  thread: UseStream<AgentThreadState>;
  threadContext: Omit<AgentThreadContext, "thread_id">;
  afterSubmit?: () => void;
  onUploadStart?: () => void;
  onUploadEnd?: () => void;
}) {
  const queryClient = useQueryClient();
  const callback = useCallback(
    async (message: PromptInputMessage, submitOptions?: ThreadResubmitOptions) => {
      resetTurnUsage();
      startTurnUsage();
      const text = message.text.trim();

      // Upload files first if any
      const hasFiles = message.files && message.files.length > 0;
      if (hasFiles) {
        onUploadStart?.();
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
            await uploadFiles(threadId, files);
          }
        } catch (error) {
          onUploadEnd?.();
          console.error("Failed to upload files:", error);
          const errorMessage =
            error instanceof Error ? error.message : "Failed to upload files.";
          toast.error(errorMessage);
          throw error;
        }
        onUploadEnd?.();
      }

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
            },
          ] as HumanMessage[],
        },
        {
          threadId: isNewThread ? threadId! : undefined,
          streamSubgraphs: true,
          streamResumable: submitOptions?.streamResumable ?? true,
          checkpoint: submitOptions?.checkpoint ?? undefined,
          streamMode: ["values", "messages-tuple", "custom"],
          config: {
            recursion_limit: 1000,
          },
          context: {
            ...threadContext,
            thread_id: threadId,
          },
        },
      );

      // Claim ownership of newly created threads via the gateway
      if (isNewThread && threadId) {
        try {
          await authFetch(`/api/threads/${threadId}/claim`, { method: "POST" });
        } catch (err) {
          console.error("Failed to claim thread:", err);
        }
      }

      await queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      afterSubmit?.();
    },
    [thread, isNewThread, threadId, threadContext, queryClient, afterSubmit, onUploadStart, onUploadEnd],
  );
  return callback;
}

/**
 * Fetch threads owned by the authenticated user via the gateway.
 * Returns only threads belonging to the current user (user-scoped).
 */
export function useThreads() {
  return useQuery<AgentThread[]>({
    queryKey: ["threads", "search"],
    queryFn: async () => {
      const response = await authFetch("/api/threads");
      if (!response.ok) {
        throw new Error(`Failed to fetch threads: ${response.status}`);
      }
      return response.json();
    },
    refetchOnWindowFocus: false,
  });
}

/**
 * Delete a thread via the gateway (with ownership verification).
 */
export function useDeleteThread() {
  const queryClient = useQueryClient();

  const removeFromCache = (threadId: string) => {
    queryClient.setQueriesData(
      {
        queryKey: ["threads", "search"],
        exact: false,
      },
      (oldData: Array<AgentThread>) => {
        return oldData.filter((t) => t.thread_id !== threadId);
      },
    );
  };

  return useMutation({
    mutationFn: async ({ threadId }: { threadId: string }) => {
      const response = await authFetch(`/api/threads/${threadId}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(`Failed to delete thread: ${response.status}`);
      }
    },
    onSuccess(_, { threadId }) {
      removeFromCache(threadId);
    },
    onError(error, { threadId }) {
      console.error("Failed to delete thread:", error);
      // Remove from local cache anyway so the user can clear stuck entries
      // (e.g. threads that were never fully created in the backend).
      removeFromCache(threadId);
      toast.error("Thread deleted locally. It may not have existed on the server.");
    },
  });
}

/**
 * Rename a thread via the gateway (with ownership verification).
 */
export function useRenameThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      title,
    }: {
      threadId: string;
      title: string;
    }) => {
      const response = await authFetch(`/api/threads/${threadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (!response.ok) {
        throw new Error(`Failed to rename thread: ${response.status}`);
      }
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
