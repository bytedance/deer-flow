import type { AgentThread } from "./types";
import { isThreadPinned, sortPinnedThreads } from "./utils";

const MAX_VISIBLE_THREADS = 200;
const modelCache = new WeakMap<object, ThreadListModel>();

export type ThreadListModel = {
  byId: ReadonlyMap<string, AgentThread>;
  threads: readonly AgentThread[];
  displayedThreads: readonly AgentThread[];
  canLoadMore: boolean;
};

export function buildThreadListModel(
  pages: readonly (readonly AgentThread[])[],
): ThreadListModel {
  const cacheKey = pages as object;
  const cached = modelCache.get(cacheKey);
  if (cached) return cached;

  const byId = new Map<string, AgentThread>();
  for (const page of pages) {
    for (const thread of page) {
      if (!byId.has(thread.thread_id)) {
        byId.set(thread.thread_id, thread);
      }
    }
  }
  const threads = [...byId.values()];
  const sortedThreads = sortPinnedThreads(threads);
  const pinnedThreads = sortedThreads.filter(isThreadPinned);
  const recentThreads = sortedThreads
    .filter((thread) => !isThreadPinned(thread))
    .slice(0, MAX_VISIBLE_THREADS);
  const model: ThreadListModel = {
    byId,
    threads: sortedThreads,
    displayedThreads: [...pinnedThreads, ...recentThreads],
    canLoadMore: recentThreads.length < MAX_VISIBLE_THREADS,
  };
  modelCache.set(cacheKey, model);
  return model;
}
