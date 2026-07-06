import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ThreadTokenUsageResponse } from "./types";

export type ThreadBranchResponse = {
  thread_id: string;
  parent_thread_id: string;
  parent_checkpoint_id: string;
  branched_from_message_id: string;
  workspace_clone_mode: string;
};

export type BranchThreadFromTurnInput = {
  messageId: string;
  messageIds?: string[];
  title?: string;
};

async function readThreadAPIError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Fall through to the caller-provided message.
  }
  return fallback;
}

export async function fetchThreadTokenUsage(
  threadId: string,
): Promise<ThreadTokenUsageResponse | null> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/token-usage`,
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    if (response.status === 403 || response.status === 404) {
      return null;
    }
    throw new Error("Failed to load thread token usage.");
  }

  return (await response.json()) as ThreadTokenUsageResponse;
}

export async function branchThreadFromTurn(
  threadId: string,
  input: BranchThreadFromTurnInput,
): Promise<ThreadBranchResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/branches`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message_id: input.messageId,
        message_ids: input.messageIds ?? [input.messageId],
        ...(input.title ? { title: input.title } : {}),
      }),
    },
  );

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to branch conversation."),
    );
  }

  return (await response.json()) as ThreadBranchResponse;
}
