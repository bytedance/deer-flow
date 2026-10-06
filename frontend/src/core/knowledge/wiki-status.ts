/**
 * Pure derivations over the wiki entries payload (wiki 更新状态可见,
 * 2026-08-14). The polling cadence lives here — like document-stats.ts — so
 * the hook wiring stays trivially testable.
 */
import { DOCUMENTS_POLL_INTERVAL_MS } from "./document-stats";
import type { WikiEntriesPage } from "./types";

/**
 * Polling cadence for the wiki entries list while a generation run is in
 * flight — aliased from the documents query's cadence so the two library
 * pipelines can never drift apart (code-review 2026-08-14).
 */
export const WIKI_ENTRIES_POLL_INTERVAL_MS = DOCUMENTS_POLL_INTERVAL_MS;

/**
 * TanStack Query ``refetchInterval`` decision for the wiki entries query:
 * poll only while the library-level generation flag reports a run in
 * flight; idle lists never poll. ``updating`` covers the click→first-poll
 * gap — the 202 ack returns before the background task flips the flag, so
 * the caller ORs in the mutation's pending state.
 */
export function wikiEntriesRefetchInterval(page: WikiEntriesPage | undefined): number | false {
  if (!page) return false;
  return page.generation === "generating" ? WIKI_ENTRIES_POLL_INTERVAL_MS : false;
}

/** True while the wiki tab should render 更新中 (run in flight or just triggered). */
export function isWikiUpdating(page: WikiEntriesPage | undefined, mutationPending: boolean): boolean {
  return mutationPending || page?.generation === "generating";
}
