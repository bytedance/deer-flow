import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  controlSubagentBatch,
  fetchSubagentBatchItems,
  fetchSubagentBatches,
  retrySubagentBatchItem,
} from "./api";
import { isActiveSubagentBatch } from "./types";

export const subagentBatchesKey = (threadId: string) =>
  ["subagent-batches", threadId] as const;
export const subagentBatchItemsKey = (threadId: string, batchId: string) =>
  [...subagentBatchesKey(threadId), batchId, "items"] as const;

export function useSubagentBatches(
  threadId: string,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: subagentBatchesKey(threadId),
    queryFn: () => fetchSubagentBatches(threadId),
    enabled: options.enabled !== false && Boolean(threadId),
    refetchInterval: (query) =>
      query.state.data?.some(isActiveSubagentBatch) ? 2000 : 15000,
    refetchIntervalInBackground: false,
  });
}

export function useSubagentBatchItems(
  threadId: string,
  batchId: string,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: subagentBatchItemsKey(threadId, batchId),
    queryFn: () => fetchSubagentBatchItems(threadId, batchId),
    enabled: options.enabled !== false && Boolean(threadId) && Boolean(batchId),
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
  });
}

export function useControlSubagentBatch(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      batchId,
      action,
    }: {
      batchId: string;
      action: "pause" | "resume" | "cancel";
    }) => controlSubagentBatch(threadId, batchId, action),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: subagentBatchesKey(threadId) }),
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useRetrySubagentBatchItem(threadId: string, batchId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId: string) =>
      retrySubagentBatchItem(threadId, batchId, itemId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: subagentBatchesKey(threadId),
      });
      void queryClient.invalidateQueries({
        queryKey: subagentBatchItemsKey(threadId, batchId),
      });
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
