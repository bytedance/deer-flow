import { getBackendBaseURL } from "../config";

import type {
  CreateThreadBranchRequest,
  CreateThreadBranchResponse,
  ThreadRecord,
} from "./types";

export async function fetchThreadRecord(
  threadId: string,
): Promise<ThreadRecord> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
  );

  if (!response.ok) {
    throw new Error("Failed to fetch thread.");
  }

  return (await response.json()) as ThreadRecord;
}

export async function createThreadBranch(
  threadId: string,
  body: CreateThreadBranchRequest,
): Promise<CreateThreadBranchResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/branches`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    },
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to create thread branch." }));
    throw new Error(error.detail ?? "Failed to create thread branch.");
  }

  return (await response.json()) as CreateThreadBranchResponse;
}
