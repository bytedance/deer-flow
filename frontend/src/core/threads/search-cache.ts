import type { InfiniteData } from "@tanstack/react-query";

import type { AgentThread } from "./types";

/**
 * Paged shape that ``useThreads`` stores under ``["threads", "search", …]``.
 *
 * The thread list is fetched one page at a time, so every cache writer has to
 * round-trip through this structure (mapping over ``pages``) instead of a flat
 * array. These helpers are kept pure so they can be unit-tested without React
 * and so the ``setQueriesData`` call sites in ``hooks.ts`` stay in lockstep.
 */
export type ThreadSearchCache = InfiniteData<AgentThread[], number> | undefined;

/** Apply ``patch`` to the matching thread in every page of the search cache. */
export function patchThreadInSearchCache(
  data: ThreadSearchCache,
  threadId: string,
  patch: (thread: AgentThread) => AgentThread,
): ThreadSearchCache {
  if (!data) {
    return data;
  }
  return {
    ...data,
    pages: data.pages.map((page) =>
      page.map((thread) =>
        thread.thread_id === threadId ? patch(thread) : thread,
      ),
    ),
  };
}

/** Drop the matching thread from every page of the search cache. */
export function removeThreadFromSearchCache(
  data: ThreadSearchCache,
  threadId: string,
): ThreadSearchCache {
  if (!data) {
    return data;
  }
  return {
    ...data,
    pages: data.pages.map((page) =>
      page.filter((thread) => thread.thread_id !== threadId),
    ),
  };
}

/**
 * Insert ``thread`` at the top of the search cache, or merge it in place if a
 * thread with the same id is already loaded on some page. A brand-new thread
 * lands on the first page so it shows at the top of the most-recent list.
 */
export function upsertThreadIntoSearchCache(
  data: ThreadSearchCache,
  thread: AgentThread,
): InfiniteData<AgentThread[], number> {
  if (!data) {
    return { pages: [[thread]], pageParams: [0] };
  }

  const exists = data.pages.some((page) =>
    page.some((t) => t.thread_id === thread.thread_id),
  );

  if (!exists) {
    const [firstPage = [], ...restPages] = data.pages;
    return {
      ...data,
      pages: [[thread, ...firstPage], ...restPages],
    };
  }

  return {
    ...data,
    pages: data.pages.map((page) =>
      page.map((t) => {
        if (t.thread_id !== thread.thread_id) {
          return t;
        }
        return {
          ...thread,
          ...t,
          metadata: {
            ...(thread.metadata ?? {}),
            ...(t.metadata ?? {}),
          },
          values: {
            ...thread.values,
            ...t.values,
          },
        };
      }),
    ),
  };
}
