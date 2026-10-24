import {
  requestWithWorkspace,
  type WorkspaceRequestOptions,
} from "@/core/api/request";
import { getBackendBaseURL } from "@/core/config";

import type { WorkspaceChangesResponse } from "./types";

export async function fetchWorkspaceChanges(
  {
    threadId,
    runId,
    includeFiles = true,
    includeDiff = true,
  }: {
    threadId: string;
    runId: string;
    includeFiles?: boolean;
    includeDiff?: boolean;
  },
  options?: WorkspaceRequestOptions,
): Promise<WorkspaceChangesResponse> {
  const query = new URLSearchParams({
    include_files: includeFiles ? "true" : "false",
    include_diff: includeDiff ? "true" : "false",
  });
  return requestWithWorkspace(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
      threadId,
    )}/runs/${encodeURIComponent(runId)}/workspace-changes?${query}`,
    undefined,
    async (response) => {
      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Failed to load workspace changes." }));
        throw new Error(error.detail ?? "Failed to load workspace changes.");
      }

      return response.json() as Promise<WorkspaceChangesResponse>;
    },
    options,
  );
}
