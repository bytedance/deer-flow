import { describe, expect, it } from "vitest";

import type { InteractionState, UIBlock } from "@/core/genui/store";
import {
  buildStreamingBlockExclusions,
  partitionStandaloneBlockIds,
} from "@/core/genui/visibility";

function makeBlock(
  block_id: string,
  overrides: Partial<UIBlock> = {},
): UIBlock {
  return {
    schema_version: "1.0",
    type: "ui_block",
    action: "create",
    block_id,
    component: "table",
    props: {},
    interactive: false,
    ...overrides,
  };
}

function makeBlocksMap(blocks: UIBlock[]): Map<string, UIBlock> {
  return new Map(blocks.map((b) => [b.block_id, b]));
}

describe("partitionStandaloneBlockIds", () => {
  it("places non-interactive store-only blocks in tail (visible on refresh)", () => {
    const block = makeBlock("table-1");

    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [],
      liveMessageBlockIds: [],
      preStreamBlockIds: [],
      blocks: makeBlocksMap([block]),
      interactions: new Map<string, InteractionState>(),
    });

    expect(result.historicalBlockIds).toEqual([]);
    expect(result.tailBlockIds).toEqual([block.block_id]);
  });

  it("hides recovered-only interactive forms on refresh (no message anchor, no stream boundary)", () => {
    const block = makeBlock("form-1", {
      component: "form",
      interactive: true,
      callback_id: "cb-1",
    });

    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [],
      liveMessageBlockIds: [],
      preStreamBlockIds: [], // empty → no stream boundary → hides stale interactive
      blocks: makeBlocksMap([block]),
      interactions: new Map<string, InteractionState>(),
    });

    expect(result.historicalBlockIds).toEqual([]);
    expect(result.tailBlockIds).toEqual([]);
  });

  it("keeps interactive blocks that arrived during an active stream", () => {
    const block = makeBlock("form-1", {
      component: "form",
      interactive: true,
      callback_id: "cb-1",
    });

    // preStream is non-empty → hasStreamBoundary=true
    // block not in preStream → wasPresentBeforeStream=false
    // → condition (wasPresentBeforeStream || !hasStreamBoundary) = false → NOT hidden
    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [],
      liveMessageBlockIds: [],
      preStreamBlockIds: ["other-block"],
      blocks: makeBlocksMap([block]),
      interactions: new Map<string, InteractionState>(),
    });

    // Falls through to tail since no message anchor and not pre-stream
    expect(result.tailBlockIds).toEqual([block.block_id]);
  });

  it("places blocks with historical message anchor in historicalBlockIds", () => {
    const block = makeBlock("chart-1");

    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [block.block_id],
      liveMessageBlockIds: [],
      preStreamBlockIds: ["chart-1"],
      blocks: makeBlocksMap([block]),
      interactions: new Map<string, InteractionState>(),
    });

    expect(result.historicalBlockIds).toEqual([block.block_id]);
    expect(result.tailBlockIds).toEqual([]);
  });

  it("places blocks with live message anchor in tailBlockIds", () => {
    const block = makeBlock("chart-2");

    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [],
      liveMessageBlockIds: [block.block_id],
      preStreamBlockIds: [],
      blocks: makeBlocksMap([block]),
      interactions: new Map<string, InteractionState>(),
    });

    expect(result.historicalBlockIds).toEqual([]);
    expect(result.tailBlockIds).toEqual([block.block_id]);
  });

  it("excludes claimed blocks from both buckets", () => {
    const block = makeBlock("inline-1");

    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [block.block_id],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [block.block_id],
      liveMessageBlockIds: [],
      preStreamBlockIds: [],
      blocks: makeBlocksMap([block]),
      interactions: new Map<string, InteractionState>(),
    });

    expect(result.historicalBlockIds).toEqual([]);
    expect(result.tailBlockIds).toEqual([]);
  });

  it("excludes submitted interactive blocks", () => {
    const block = makeBlock("form-submitted", {
      component: "form",
      interactive: true,
      callback_id: "cb-submitted",
    });

    const interactions = new Map<string, InteractionState>();
    interactions.set("cb-submitted", { status: "submitted" });

    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [block.block_id],
      liveMessageBlockIds: [],
      preStreamBlockIds: [],
      blocks: makeBlocksMap([block]),
      interactions,
    });

    expect(result.historicalBlockIds).toEqual([]);
    expect(result.tailBlockIds).toEqual([]);
  });

  it("places recovered blocks from pre-stream in historical when they have no message anchor", () => {
    const block = makeBlock("old-chart");

    const result = partitionStandaloneBlockIds({
      claimedBlockIds: [],
      storeBlockIds: [block.block_id],
      historicalMessageBlockIds: [],
      liveMessageBlockIds: [],
      preStreamBlockIds: [block.block_id], // was present before stream
      blocks: makeBlocksMap([block]),
      interactions: new Map<string, InteractionState>(),
    });

    // !hasMessageAnchor && wasPresentBeforeStream → historical
    expect(result.historicalBlockIds).toEqual([block.block_id]);
    expect(result.tailBlockIds).toEqual([]);
  });
});

describe("buildStreamingBlockExclusions", () => {
  it("combines and deduplicates block ID groups", () => {
    expect(
      buildStreamingBlockExclusions(
        ["old-block", "current-block", "current-block"],
      ),
    ).toEqual(["old-block", "current-block"]);
  });

  it("handles multiple groups", () => {
    expect(
      buildStreamingBlockExclusions(
        ["a", "b"],
        ["c", "a"],
      ),
    ).toEqual(["a", "b", "c"]);
  });
});
