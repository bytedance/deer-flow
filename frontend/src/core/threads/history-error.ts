import type { ThreadsClient } from "@langchain/langgraph-sdk/client";

/**
 * Errors thrown while fetching a thread's history. The SDK reports them
 * through the stream's `onError` without run metadata, exactly like a refused
 * run request, but unlike a refusal the run can still be created afterwards.
 */
const historyErrors = new WeakSet<object>();

export function markHistoryError(error: unknown): void {
  if (typeof error === "object" && error !== null) {
    historyErrors.add(error);
  }
}

/** True when `error` came from a history fetch rather than from a run request. */
export function isHistoryError(error: unknown): boolean {
  return (
    typeof error === "object" && error !== null && historyErrors.has(error)
  );
}

type TaggedThreads = {
  getHistory: (...args: unknown[]) => Promise<unknown>;
  __tagsHistoryErrors?: boolean;
};

type HistoryClient = { threads: ThreadsClient };

/**
 * Tag errors thrown by `threads.getHistory` so a stream `onError` can tell a
 * failed history fetch from a refused run request. Both arrive without run
 * metadata; only the refusal means the send never became a turn.
 */
export function withHistoryErrorTagging<T extends HistoryClient>(client: T): T {
  const threads = client.threads as unknown as TaggedThreads | undefined;
  // Test doubles and non-SDK clients may not expose a history reader; leave
  // them untouched so `onError` falls back to its normal settlement.
  if (
    !threads ||
    typeof threads.getHistory !== "function" ||
    threads.__tagsHistoryErrors
  ) {
    return client;
  }
  const getHistory = threads.getHistory.bind(threads);
  threads.getHistory = async (...args: unknown[]) => {
    try {
      return await getHistory(...args);
    } catch (error) {
      markHistoryError(error);
      throw error;
    }
  };
  threads.__tagsHistoryErrors = true;
  return client;
}
