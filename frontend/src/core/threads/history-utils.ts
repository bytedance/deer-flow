import type { Message } from "@langchain/langgraph-sdk";

/**
 * Deduplicate incoming messages against an existing history.
 * A message is considered a duplicate if its `id` or `tool_call_id`
 * (for tool messages) already appears in the existing list.
 */
export function deduplicateHistoryMessages(
  existing: Message[],
  incoming: Message[],
): Message[] {
  const existingIds = new Set(
    existing
      .map((m) => ("tool_call_id" in m ? m.tool_call_id : m.id))
      .filter(Boolean),
  );

  return incoming.filter((m) => {
    if (m.id && existingIds.has(m.id)) return false;
    if (
      "tool_call_id" in m &&
      m.tool_call_id &&
      existingIds.has(m.tool_call_id)
    ) {
      return false;
    }
    return true;
  });
}

/**
 * Compute the new history-loading index when the runs list grows.
 *
 * - `currentIndex < 0` means all previously-known runs have been loaded;
 *   reset to the last run so the user can scroll up to load new runs.
 * - `currentIndex >= 0` means some runs haven't been loaded yet;
 *   shift the index by the number of newly-added runs.
 * - If no new runs were added, return `currentIndex` unchanged.
 */
export function adjustHistoryIndex(
  currentIndex: number,
  prevRunsLength: number,
  newRunsLength: number,
): number {
  const added = newRunsLength - prevRunsLength;
  if (added <= 0) return currentIndex;
  if (currentIndex < 0) return newRunsLength - 1;
  return currentIndex + added;
}
