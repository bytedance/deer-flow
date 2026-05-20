import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ThreadTokenUsageResponse } from "./types";

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

export interface ClearContextResponse {
  success: boolean;
  message: string;
  checkpoint_id: string | null;
}

export interface CompactContextResponse {
  success: boolean;
  message: string;
  summary: string | null;
  checkpoint_id: string | null;
}

export async function clearThreadContext(
  threadId: string,
): Promise<ClearContextResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/clear-context`,
    { method: "POST" },
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to clear context." }));
    throw new Error(error.detail ?? "Failed to clear context.");
  }

  return (await response.json()) as ClearContextResponse;
}

export async function compactThreadContext(
  threadId: string,
): Promise<CompactContextResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/compact`,
    { method: "POST" },
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to compact context." }));
    throw new Error(error.detail ?? "Failed to compact context.");
  }

  return (await response.json()) as CompactContextResponse;
}
