import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { perfMetrics } from "@/core/perf/metrics";

describe("perfMetrics", () => {
  beforeEach(() => {
    perfMetrics.start();
  });

  afterEach(() => {
    perfMetrics.stop();
    perfMetrics.reset();
  });

  it("tracks SSE connection increments and decrements", () => {
    expect(perfMetrics.snapshot().activeSSEConnections).toBe(0);

    perfMetrics.incrementSSE();
    perfMetrics.incrementSSE();
    expect(perfMetrics.snapshot().activeSSEConnections).toBe(2);

    perfMetrics.decrementSSE();
    expect(perfMetrics.snapshot().activeSSEConnections).toBe(1);
  });

  it("clamps SSE count at zero", () => {
    perfMetrics.decrementSSE();
    perfMetrics.decrementSSE();
    expect(perfMetrics.snapshot().activeSSEConnections).toBe(0);
  });

  it("records ui-blocks/extract calls", () => {
    expect(perfMetrics.snapshot().uiBlocksExtractCalls).toBe(0);

    perfMetrics.recordUIBlocksExtract();
    perfMetrics.recordUIBlocksExtract();
    perfMetrics.recordUIBlocksExtract();
    expect(perfMetrics.snapshot().uiBlocksExtractCalls).toBe(3);
  });

  it("returns consistent snapshot with timestamp", () => {
    perfMetrics.incrementSSE();
    perfMetrics.recordUIBlocksExtract();

    const snap = perfMetrics.snapshot();
    expect(snap.activeSSEConnections).toBe(1);
    expect(snap.uiBlocksExtractCalls).toBe(1);
    expect(snap.timestamp).toBeGreaterThan(0);
    expect(typeof snap.longTaskCount).toBe("number");
    expect(typeof snap.longTaskTotalMs).toBe("number");
  });

  it("resets all counters", () => {
    perfMetrics.incrementSSE();
    perfMetrics.incrementSSE();
    perfMetrics.recordUIBlocksExtract();

    perfMetrics.reset();

    const snap = perfMetrics.snapshot();
    expect(snap.activeSSEConnections).toBe(0);
    expect(snap.uiBlocksExtractCalls).toBe(0);
  });

  it("start() is idempotent while running", () => {
    perfMetrics.incrementSSE();
    perfMetrics.incrementSSE();
    perfMetrics.start(); // second start is no-op (already running)
    expect(perfMetrics.snapshot().activeSSEConnections).toBe(2);
  });
});
