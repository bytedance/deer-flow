/**
 * KB-thread isolation predicates (spec §5.2 库间对话隔离).
 *
 * Threads created inside the knowledge page carry ``metadata.kb_id``
 * (written by the ``onCreated`` hook in `core/threads/hooks.ts`). The global
 * recent-chat list excludes them; the per-kb history popover lists exactly
 * the bound kb's threads.
 */

/** Thread metadata key linking a conversation to a knowledge base. */
export const KB_ID_METADATA_KEY = "kb_id";

interface ThreadWithMetadata {
  metadata?: Record<string, unknown> | null;
}

export function kbIdOfThread(thread: ThreadWithMetadata): string | null {
  const value = thread.metadata?.[KB_ID_METADATA_KEY];
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function isKnowledgeThread(thread: ThreadWithMetadata): boolean {
  return kbIdOfThread(thread) !== null;
}

export function excludeKnowledgeThreads<T extends ThreadWithMetadata>(threads: readonly T[]): T[] {
  return threads.filter((thread) => !isKnowledgeThread(thread));
}

export function threadsForKb<T extends ThreadWithMetadata>(threads: readonly T[], kbId: string): T[] {
  return threads.filter((thread) => kbIdOfThread(thread) === kbId);
}
