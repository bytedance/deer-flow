import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  RunMessage,
  RunMessagesPage,
  ThreadTokenUsageResponse,
} from "./types";

function hasMoreRunMessages(page: RunMessagesPage): boolean {
  return page.has_more === true || page.hasMore === true;
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

export async function fetchRunHistoryMessages(
  threadId: string,
  runId: string,
): Promise<RunMessage[]> {
  const allMessages: RunMessage[] = [];
  let beforeSeq: number | undefined;

  while (true) {
    const params = new URLSearchParams();
    if (beforeSeq !== undefined) {
      params.set("before_seq", String(beforeSeq));
    }

    const query = params.size > 0 ? `?${params.toString()}` : "";
    const response = await fetchWithAuth(
      `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/messages${query}`,
      {
        method: "GET",
      },
    );
    if (!response.ok) {
      if (response.status === 403 || response.status === 404) {
        break;
      }
      throw new Error("Failed to load run history messages.");
    }

    const page = (await response.json()) as RunMessagesPage;

    allMessages.unshift(...page.data);

    if (!hasMoreRunMessages(page) || page.data.length === 0) {
      break;
    }

    const earliestSeq = page.data[0]?.seq;
    if (typeof earliestSeq !== "number") {
      break;
    }
    beforeSeq = earliestSeq;
  }

  return allMessages;
}
