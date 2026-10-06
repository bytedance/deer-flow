/**
 * Tick window clamping for the chunk minimap rail (2026-09-05 切片导航):
 * the collapsed rail renders only a window of ticks around the active chunk;
 * the window must stay in bounds and never leave the visible band half empty
 * at the document head/tail.
 */
import { describe, expect, it } from "@rstest/core";

import { tickRange } from "@/components/workspace/knowledge/chunk-tick-rail";

describe("tickRange", () => {
  it("returns an empty window for an empty document", () => {
    expect(tickRange(0, 0)).toEqual({ start: 0, end: 0 });
  });

  it("centers the window around the active tick mid-document", () => {
    expect(tickRange(50, 100)).toEqual({ start: 40, end: 61 });
  });

  it("clamps at the document head while filling the visible band", () => {
    expect(tickRange(0, 100)).toEqual({ start: 0, end: 11 });
  });

  it("clamps at the document tail", () => {
    expect(tickRange(99, 100)).toEqual({ start: 89, end: 100 });
  });

  it("covers every tick of a short document", () => {
    expect(tickRange(2, 5)).toEqual({ start: 0, end: 5 });
  });

  it("clamps an out-of-range active index to the nearest bound", () => {
    expect(tickRange(150, 100)).toEqual(tickRange(99, 100));
    expect(tickRange(-3, 100)).toEqual(tickRange(0, 100));
  });
});
