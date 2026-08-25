import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
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
const SUBAGENT_BATCH_ITEMS_PAGE_SIZE = 100;

export function useSubagentBatches(
  threadId: string,
  options: { enabled?: boolean; polling?: boolean } = {},
) {
  return useQuery({
    queryKey: subagentBatchesKey(threadId),
    queryFn: () => fetchSubagentBatches(threadId),
    enabled: options.enabled !== false && Boolean(threadId),
    refetchInterval: (query) => {
      if (options.polling === false) return false;
      return query.state.data?.some(isActiveSubagentBatch) ? 2000 : 15000;
    },
    refetchIntervalInBackground: false,
  });
}

export function useSubagentBatchItems(
  threadId: string,
  batchId: string,
  options: { enabled?: boolean; polling?: boolean } = {},
) {
  return useInfiniteQuery({
    queryKey: subagentBatchItemsKey(threadId, batchId),
    queryFn: ({ pageParam }) =>
      fetchSubagentBatchItems(threadId, batchId, {
        offset: pageParam,
        limit: SUBAGENT_BATCH_ITEMS_PAGE_SIZE,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === SUBAGENT_BATCH_ITEMS_PAGE_SIZE
        ? allPages.reduce((total, page) => total + page.length, 0)
        : undefined,
    enabled: options.enabled !== false && Boolean(threadId) && Boolean(batchId),
    // React Query refetches every loaded infinite page. Keep live polling for
    // the bounded first page, then stop automatic fan-out after the user loads
    // more; window-focus/manual invalidation still refreshes the loaded pages.
    refetchInterval: (query) => {
      if (options.polling === false) return false;
      return (query.state.data?.pages.length ?? 0) <= 1 ? 3000 : false;
    },
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
