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
  checkpoint_id?: string | null;
}

export interface CompactContextResponse extends ClearContextResponse {
  summary: string;
}

async function _readDetail(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: string };
    return typeof body?.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}

export async function clearThreadContext(
  threadId: string,
): Promise<ClearContextResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/clear-context`,
    { method: "POST" },
  );
  if (!response.ok) {
    const detail = await _readDetail(response);
    throw new Error(detail ?? "Failed to clear context.");
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
    const detail = await _readDetail(response);
    throw new Error(detail ?? "Failed to compact context.");
  }
  return (await response.json()) as CompactContextResponse;
}
