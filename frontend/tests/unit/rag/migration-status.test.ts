/**
 * 宽度迁移的纯派生（spec 2026-09-26 D5-7）：轮询节奏与"在飞"判定。
 * 与 `knowledge/reindex-status.ts` 同形 —— 只在真的在跑时轮询，空闲一次都不打。
 */
import { describe, expect, it } from "@rstest/core";

import {
  isMigrationRunning,
  MIGRATION_POLL_INTERVAL_MS,
  migrationRefetchInterval,
} from "@/core/rag/migration-status";
import type { RagMigrationStatus } from "@/core/rag/types";

function status(state: RagMigrationStatus["state"]): RagMigrationStatus {
  return { state, target_dimension: 1536, detail: null, progress: null };
}

describe("migration-status", () => {
  it("polls only while a migration is running", () => {
    expect(migrationRefetchInterval(status("running"))).toBe(
      MIGRATION_POLL_INTERVAL_MS,
    );
    expect(migrationRefetchInterval(status("succeeded"))).toBe(false);
    expect(migrationRefetchInterval(status("failed"))).toBe(false);
  });

  it("asks nothing when no migration ever ran", () => {
    expect(migrationRefetchInterval(undefined)).toBe(false);
    expect(migrationRefetchInterval(null)).toBe(false);
  });

  it("counts only `running` as in flight", () => {
    expect(isMigrationRunning(status("running"))).toBe(true);
    expect(isMigrationRunning(status("succeeded"))).toBe(false);
    expect(isMigrationRunning(null)).toBe(false);
    expect(isMigrationRunning(undefined)).toBe(false);
  });
});
