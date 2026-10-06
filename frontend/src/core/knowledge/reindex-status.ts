/**
 * Pure derivations over the rebuild-status payload (spec 2026-09-14 §5 / P4). The
 * polling cadence lives here — like wiki-status.ts and document-stats.ts — so the hook
 * wiring stays trivially testable.
 */
import { DOCUMENTS_POLL_INTERVAL_MS } from "./document-stats";
import type { ReindexStatus } from "./types";

/** Aliased from the documents query's cadence so the library pipelines never drift apart. */
export const REINDEX_POLL_INTERVAL_MS = DOCUMENTS_POLL_INTERVAL_MS;

/** Poll only while a rebuild reports itself in flight; an idle entry never polls. */
export function reindexRefetchInterval(
  status: ReindexStatus | undefined,
): number | false {
  if (!status) return false;
  return status.in_progress ? REINDEX_POLL_INTERVAL_MS : false;
}

/**
 * True while the entry should render as running. ``pending`` covers the click→first-poll
 * gap: the 202 ack returns before the background task flips the flag, so the caller ORs in
 * the mutation's pending state.
 */
export function isReindexRunning(
  status: ReindexStatus | undefined,
  pending: boolean,
): boolean {
  return pending || status?.in_progress === true;
}
