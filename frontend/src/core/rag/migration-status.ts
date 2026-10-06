/**
 * Pure derivations over the width-migration payload (spec 2026-09-26 D5-7). The polling
 * cadence lives here — like `knowledge/reindex-status.ts` — so the hook wiring stays
 * trivially testable.
 */
import { REINDEX_POLL_INTERVAL_MS } from "@/core/knowledge/reindex-status";

import type { RagMigrationStatus } from "./types";

/** Aliased from the rebuild's cadence: both are "a server-side job, poll while it runs". */
export const MIGRATION_POLL_INTERVAL_MS = REINDEX_POLL_INTERVAL_MS;

/** Poll only while a migration reports itself running; a settled verdict never polls. */
export function migrationRefetchInterval(
  status: RagMigrationStatus | null | undefined,
): number | false {
  return status?.state === "running" ? MIGRATION_POLL_INTERVAL_MS : false;
}

export function isMigrationRunning(
  status: RagMigrationStatus | null | undefined,
): boolean {
  return status?.state === "running";
}
