import type { AgentThread } from "./types";
import { isThreadPinned } from "./utils";

const THREAD_BRANCH_METADATA_KEY = "deerflow_branch";
const THREAD_BRANCH_PARENT_METADATA_KEY = "branch_parent_thread_id";

export type ThreadBranchEntry = {
  thread: AgentThread;
  parentThread?: AgentThread;
  depth: number;
  isLastSibling: boolean;
};

function recencyOfThread(thread: AgentThread) {
  const timestamp = Date.parse(thread.updated_at ?? thread.created_at ?? "");
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function branchParentId(thread: AgentThread) {
  if (thread.metadata?.[THREAD_BRANCH_METADATA_KEY] !== true) {
    return null;
  }
  const parentId = thread.metadata?.[THREAD_BRANCH_PARENT_METADATA_KEY];
  if (typeof parentId !== "string") {
    return null;
  }
  return parentId.trim() || null;
}

/**
 * Project the loaded flat thread page into a safe visual lineage.
 *
 * Only loaded parents in the same pinned partition can own a child. Missing,
 * malformed, cross-pin, self-parented, and cyclic links remain top-level so
 * partial pagination or bad metadata can never hide a conversation.
 */
export function flattenThreadBranches(
  threads: readonly AgentThread[],
): ThreadBranchEntry[] {
  if (threads.length < 2) {
    return threads.map((thread) => ({
      thread,
      depth: 0,
      isLastSibling: true,
    }));
  }

  const byId = new Map(threads.map((thread) => [thread.thread_id, thread]));
  const sourceIndex = new Map(
    threads.map((thread, index) => [thread.thread_id, index]),
  );
  const candidateParentByChild = new Map<string, string>();

  for (const thread of threads) {
    const parentId = branchParentId(thread);
    const parent = parentId ? byId.get(parentId) : undefined;
    if (
      !parent ||
      parent.thread_id === thread.thread_id ||
      isThreadPinned(parent) !== isThreadPinned(thread)
    ) {
      continue;
    }
    candidateParentByChild.set(thread.thread_id, parent.thread_id);
  }

  const hasCyclicAncestry = (threadId: string) => {
    const visited = new Set<string>([threadId]);
    let parentId = candidateParentByChild.get(threadId);
    while (parentId) {
      if (visited.has(parentId)) {
        return true;
      }
      visited.add(parentId);
      parentId = candidateParentByChild.get(parentId);
    }
    return false;
  };

  const parentByChild = new Map<string, string>();
  for (const [childId, parentId] of candidateParentByChild) {
    if (!hasCyclicAncestry(childId)) {
      parentByChild.set(childId, parentId);
    }
  }

  const childrenByParent = new Map<string, AgentThread[]>();
  for (const thread of threads) {
    const parentId = parentByChild.get(thread.thread_id);
    if (!parentId) continue;
    const children = childrenByParent.get(parentId) ?? [];
    children.push(thread);
    childrenByParent.set(parentId, children);
  }

  for (const [parentId, children] of childrenByParent) {
    const parent = byId.get(parentId);
    if (!parent || isThreadPinned(parent)) continue;
    children.sort(
      (left, right) =>
        recencyOfThread(right) - recencyOfThread(left) ||
        (sourceIndex.get(left.thread_id) ?? 0) -
          (sourceIndex.get(right.thread_id) ?? 0),
    );
  }

  const groupRecencyCache = new Map<string, number>();
  const groupRecency = (thread: AgentThread): number => {
    const cached = groupRecencyCache.get(thread.thread_id);
    if (cached !== undefined) return cached;
    const recency = (childrenByParent.get(thread.thread_id) ?? []).reduce(
      (latest, child) => Math.max(latest, groupRecency(child)),
      recencyOfThread(thread),
    );
    groupRecencyCache.set(thread.thread_id, recency);
    return recency;
  };

  const roots = threads.filter(
    (thread) => !parentByChild.has(thread.thread_id),
  );
  roots.sort((left, right) => {
    const pinnedDifference =
      Number(isThreadPinned(right)) - Number(isThreadPinned(left));
    if (pinnedDifference) return pinnedDifference;
    if (isThreadPinned(left)) {
      return (
        (sourceIndex.get(left.thread_id) ?? 0) -
        (sourceIndex.get(right.thread_id) ?? 0)
      );
    }
    return (
      groupRecency(right) - groupRecency(left) ||
      (sourceIndex.get(left.thread_id) ?? 0) -
        (sourceIndex.get(right.thread_id) ?? 0)
    );
  });

  const entries: ThreadBranchEntry[] = [];
  const emitted = new Set<string>();
  const emit = (
    thread: AgentThread,
    depth: number,
    isLastSibling: boolean,
    parentThread?: AgentThread,
  ) => {
    if (emitted.has(thread.thread_id)) return;
    emitted.add(thread.thread_id);
    entries.push({ thread, parentThread, depth, isLastSibling });
    const children = childrenByParent.get(thread.thread_id) ?? [];
    children.forEach((child, index) =>
      emit(child, depth + 1, index === children.length - 1, thread),
    );
  };

  roots.forEach((root) => emit(root, 0, true));
  // Defense in depth: no malformed lineage should make a loaded thread vanish.
  threads.forEach((thread) => emit(thread, 0, true));
  return entries;
}
