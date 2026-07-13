import type { Message } from "@langchain/langgraph-sdk";

import { messageIdentity } from "./message-identity";

/**
 * Deduplicate incoming messages against an existing history.
 *
 * Each message is keyed by a stable per-message identity (see
 * `messageIdentity`), which namespaces tool messages under `tool:<id>` and
 * other messages under `message:<id>` so an AI message whose `id` happens to
 * match a tool's `tool_call_id` is not incorrectly dropped.
 *
 * Messages without a usable identity are passed through unchanged.
 */
export function deduplicateHistoryMessages(
  existing: Message[],
  incoming: Message[],
): Message[] {
  const existingKeys = new Set<string>(
    existing.map(messageIdentity).filter((key): key is string => Boolean(key)),
  );

  return incoming.filter((m) => {
    const key = messageIdentity(m);
    if (!key) return true;
    return !existingKeys.has(key);
  });
}

/**
 * Compute the new history-loading index when the runs list grows.
 *
 * Assumes the runs list is ordered **newest-first** (descending by
 * `updated_at`), so newly-fetched runs are *prepended* at index 0 rather than
 * appended at the end.
 *
 * - `added <= 0` (no new runs): return `currentIndex` unchanged.
 * - `currentIndex < 0` (all previously-known runs were loaded):
 *   - if there were no previous runs (`prevRunsLength === 0`), land on the
 *     newest run at index 0;
 *   - otherwise the user was on the previous newest (old index 0), which
 *     after `added` prepends is now at index `added`.
 * - `currentIndex >= 0` (some runs were unloaded): the user's run shifts down
 *   by `added`, so return `currentIndex + added`.
 */
export function adjustHistoryIndex(
  currentIndex: number,
  prevRunsLength: number,
  newRunsLength: number,
): number {
  const added = newRunsLength - prevRunsLength;
  if (added <= 0) return currentIndex;
  if (currentIndex < 0) {
    return prevRunsLength === 0 ? 0 : added;
  }
  return currentIndex + added;
}
