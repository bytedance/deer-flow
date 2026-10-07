/**
 * 重建索引的轮询节奏与「在跑」判据（spec 2026-09-14 §5 / P4）。与 wiki-status.test.ts
 * 同形：纯函数钉住节奏，hook 只做接线。
 */
import { describe, expect, it } from "@rstest/core";

import { DOCUMENTS_POLL_INTERVAL_MS } from "@/core/knowledge/document-stats";
import {
  isReindexRunning,
  REINDEX_POLL_INTERVAL_MS,
  reindexRefetchInterval,
} from "@/core/knowledge/reindex-status";
import type { ReindexStatus } from "@/core/knowledge/types";

const IDLE: ReindexStatus = {
  in_progress: false,
  last_run: null,
  progress: null,
};
const RUNNING: ReindexStatus = {
  in_progress: true,
  last_run: null,
  progress: {
    documents_total: 7,
    documents_done: 3,
    chunks_indexed: 42,
  },
};

describe("reindexRefetchInterval", () => {
  it("never polls before the first payload lands or while idle", () => {
    expect(reindexRefetchInterval(undefined)).toBe(false);
    expect(reindexRefetchInterval(IDLE)).toBe(false);
  });

  it("polls at the shared cadence while a rebuild is in flight", () => {
    // Same source as the documents query — the two can never drift apart.
    expect(REINDEX_POLL_INTERVAL_MS).toBe(DOCUMENTS_POLL_INTERVAL_MS);
    expect(REINDEX_POLL_INTERVAL_MS).toBe(3000);
    expect(reindexRefetchInterval(RUNNING)).toBe(REINDEX_POLL_INTERVAL_MS);
  });

  it("stops polling once the rebuild drains, even though last_run stays set", () => {
    expect(
      reindexRefetchInterval({
        in_progress: false,
        last_run: "succeeded",
        progress: null,
      }),
    ).toBe(false);
  });
});

describe("isReindexRunning", () => {
  it("covers the click→first-poll gap via the mutation's pending flag", () => {
    // The 202 ack returns before the background task flips the flag, so pending counts as running.
    expect(isReindexRunning(IDLE, true)).toBe(true);
    expect(isReindexRunning(undefined, true)).toBe(true);
  });

  it("is true only while the backend reports the run in flight", () => {
    expect(isReindexRunning(RUNNING, false)).toBe(true);
    expect(isReindexRunning(IDLE, false)).toBe(false);
    expect(isReindexRunning(undefined, false)).toBe(false);
  });
});
