import { useQuery } from "@tanstack/react-query";

import { fetchWorkspaceChanges } from "./api";
import type { WorkspaceChangesResponse } from "./types";

export function workspaceChangesQueryKey(
  threadId: string | undefined,
  runId: string | undefined,
  includeFiles: boolean,
  includeDiff: boolean,
) {
  return [
    "workspace-changes",
    threadId,
    runId,
    includeFiles,
    includeDiff,
  ] as const;
}

export function useWorkspaceChanges({
  threadId,
  runId,
  includeFiles = true,
  includeDiff = true,
  enabled = true,
}: {
  threadId?: string;
  runId?: string;
  includeFiles?: boolean;
  includeDiff?: boolean;
  enabled?: boolean;
}) {
  return useQuery<WorkspaceChangesResponse>({
    queryKey: workspaceChangesQueryKey(
      threadId,
      runId,
      includeFiles,
      includeDiff,
    ),
    queryFn: () => {
      if (!threadId || !runId) {
        throw new Error("threadId and runId are required");
      }
      return fetchWorkspaceChanges({
        threadId,
        runId,
        includeFiles,
        includeDiff,
      });
    },
    enabled: enabled && Boolean(threadId) && Boolean(runId),
    retry: false,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
