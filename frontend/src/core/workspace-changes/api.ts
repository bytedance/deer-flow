import { getBackendBaseURL } from "@/core/config";

import type { WorkspaceChangesResponse } from "./types";

export async function fetchWorkspaceChanges({
  threadId,
  runId,
  includeFiles = true,
  includeDiff = true,
}: {
  threadId: string;
  runId: string;
  includeFiles?: boolean;
  includeDiff?: boolean;
}): Promise<WorkspaceChangesResponse> {
  const query = new URLSearchParams({
    include_files: includeFiles ? "true" : "false",
    include_diff: includeDiff ? "true" : "false",
  });
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
      threadId,
    )}/runs/${encodeURIComponent(runId)}/workspace-changes?${query}`,
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to load workspace changes." }));
    throw new Error(error.detail ?? "Failed to load workspace changes.");
  }

  return response.json();
}
