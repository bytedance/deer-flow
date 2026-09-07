import { useMutation, useQueryClient } from "@tanstack/react-query";

import { patchThreadMetadata } from "./api";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  setThreadMetadataInCaches,
} from "./hooks";
import { THREAD_ARCHIVED_METADATA_KEY } from "./utils";

export function useArchiveThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      threadId,
      archived,
    }: {
      threadId: string;
      archived: boolean;
    }) =>
      patchThreadMetadata(threadId, {
        [THREAD_ARCHIVED_METADATA_KEY]: archived,
      }),
    async onSuccess(_response, { threadId, archived }) {
      // A response started before the write must not put the old state back.
      await Promise.all([
        queryClient.cancelQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        }),
        queryClient.cancelQueries({ queryKey: ["threads", "search"] }),
        queryClient.cancelQueries({
          queryKey: ["thread", "metadata", threadId],
        }),
      ]);
      setThreadMetadataInCaches(queryClient, threadId, {
        [THREAD_ARCHIVED_METADATA_KEY]: archived,
      });
      // Membership changed, so discard old offsets in both views. The current
      // conversation snapshot stays mounted and its files remain accessible.
      await Promise.all([
        queryClient.resetQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        }),
        queryClient.invalidateQueries({ queryKey: ["threads", "search"] }),
        queryClient.invalidateQueries({
          queryKey: ["thread", "metadata", threadId],
        }),
      ]);
    },
  });
}
