import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  ThreadShareCreateResponse,
  ThreadTokenUsageResponse,
} from "./types";

function formatErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object" && "msg" in item) {
          const message = (item as { msg?: unknown }).msg;
          return typeof message === "string" && message ? message : null;
        }
        return null;
      })
      .filter((message): message is string => Boolean(message));
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return null;
    }
  }
  return null;
}

export async function readErrorDetail(response: Response, fallback: string) {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = formatErrorDetail(body.detail);
    if (detail) {
      return detail;
    }
  } catch {
    // Ignore malformed error bodies and keep the stable fallback message.
  }
  return `${fallback} (${response.status})`;
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

export async function createThreadShare({
  threadId,
  messageIds,
  title,
}: {
  threadId: string;
  messageIds: string[];
  title?: string;
}): Promise<ThreadShareCreateResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/shares/threads/${encodeURIComponent(threadId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_ids: messageIds,
        title,
      }),
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Failed to create share."));
  }

  return (await response.json()) as ThreadShareCreateResponse;
}
