import { describe, expect, it } from "@rstest/core";

import {
  completedSubagentBatchItems,
  isActiveSubagentBatch,
  subagentBatchProgress,
  type SubagentBatch,
} from "@/core/subagent-batches/types";

const BATCH: SubagentBatch = {
  id: "batch-1",
  title: "Records",
  subagent_type: "general-purpose",
  status: "running",
  total_items: 10,
  max_live_items: 5,
  max_running_items: 2,
  max_attempts: 3,
  counts: {
    pending: 2,
    queued: 2,
    leased: 1,
    running: 1,
    succeeded: 2,
    failed: 1,
    cancelled: 1,
  },
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:01:00Z",
  completed_at: null,
};

describe("subagent batch progress", () => {
  it("counts only terminal items as completed progress", () => {
    expect(completedSubagentBatchItems(BATCH)).toBe(4);
    expect(subagentBatchProgress(BATCH)).toBe(40);
  });

  it("returns bounded progress for malformed persisted totals or counts", () => {
    expect(subagentBatchProgress({ ...BATCH, total_items: 0 })).toBe(0);
    expect(
      subagentBatchProgress({
        ...BATCH,
        total_items: 1,
        counts: { ...BATCH.counts, succeeded: 10 },
      }),
    ).toBe(100);
  });

  it.each(["queued", "running", "paused"] as const)(
    "treats %s as active",
    (status) => expect(isActiveSubagentBatch({ ...BATCH, status })).toBe(true),
  );

  it.each(["completed", "failed", "cancelled"] as const)(
    "treats %s as terminal",
    (status) => expect(isActiveSubagentBatch({ ...BATCH, status })).toBe(false),
  );
});
