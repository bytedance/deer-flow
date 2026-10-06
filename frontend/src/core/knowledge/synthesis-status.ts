/**
 * Pure derivations over the synthesis status payload (spec 2026-08-28 §6.2).
 * The polling cadence lives here — like eval-run-status.ts — so the hook
 * wiring stays trivially testable.
 */
import type { SynthesisStatus } from "./types";

/**
 * Polling cadence for the synthesis status while a generation run is in
 * flight — same 3s cadence as the documents/wiki/eval-runs queries; idle
 * status never polls.
 */
export const SYNTHESIS_POLL_INTERVAL_MS = 3000;

/**
 * TanStack Query ``refetchInterval`` decision for the synthesis status: poll
 * only while ``in_progress`` reports a run in flight. An undefined payload
 * means the query is disabled or not yet fetched.
 */
export function synthesisRefetchInterval(data: SynthesisStatus | undefined): number | false {
  if (!data) return false;
  return data.in_progress ? SYNTHESIS_POLL_INTERVAL_MS : false;
}
