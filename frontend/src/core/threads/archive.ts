import { useMutation, useQueryClient } from "@tanstack/react-query";

import { PROJECTS_QUERY_KEY } from "../projects/api";

import { patchThreadMetadata, type ThreadMetadataPatchResponse } from "./api";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  setThreadMetadataInCaches,
} from "./hooks";
import { THREAD_ARCHIVED_METADATA_KEY } from "./utils";

export type ArchiveThreadVariables = {
  threadId: string;
  archived: boolean;
};

export type ArchiveThreadOptions = {
  onSuccess?: (
    data: ThreadMetadataPatchResponse,
    variables: ArchiveThreadVariables,
  ) => void;
  onError?: (error: Error, variables: ArchiveThreadVariables) => void;
};

export function useArchiveThread(options: ArchiveThreadOptions = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, archived }: ArchiveThreadVariables) =>
      patchThreadMetadata(threadId, {
        [THREAD_ARCHIVED_METADATA_KEY]: archived,
      }),
    // The callback is registered at the mutation level, not per `mutate` call:
    // per-call handlers are dropped when the originating row unmounts (the
    // archived chat leaves the sidebar list mid-flight), which silently lost
    // the success toast before.
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
        // The project page's own thread list
        // ([...PROJECTS_QUERY_KEY, "threads", id, ...]) changes membership
        // with the archive flag; every other thread mutation (pin, rename,
        // delete, move, stop) invalidates this prefix, so archive must too.
        queryClient.invalidateQueries({
          queryKey: [...PROJECTS_QUERY_KEY, "threads"],
        }),
      ]);
      options.onSuccess?.(_response, { threadId, archived });
    },
    onError: (error, variables) => {
      options.onError?.(error, variables);
    },
  });
}
