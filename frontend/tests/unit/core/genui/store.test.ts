import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useBlockStore, type UIBlock } from "@/core/genui/store";

function makeBlock(id: string, component = "markdown", props: Record<string, unknown> = {}): UIBlock {
  return {
    schema_version: "1",
    type: "ui_block",
    action: "create",
    block_id: id,
    component,
    props,
    interactive: false,
  };
}

describe("useBlockStore incremental mode (2.10)", () => {
  beforeEach(() => {
    useBlockStore.getState().reset();
  });

  afterEach(() => {
    useBlockStore.getState().reset();
  });

  it("upsertBlock inserts a new block", () => {
    const block = makeBlock("block-1", "chart", { data: [1, 2, 3] });

    useBlockStore.getState().upsertBlock("test-thread", block);

    const stored = useBlockStore.getState().blocks.get("block-1");
    expect(stored).toBeDefined();
    expect(stored?.component).toBe("chart");
    expect(stored?.props).toEqual({ data: [1, 2, 3] });
  });

  it("upsertBlock updates an existing block without affecting others", () => {
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("block-1", "markdown", { content: "v1" }));
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("block-2", "chart", { data: [1] }));

    useBlockStore.getState().upsertBlock("test-thread", makeBlock("block-1", "markdown", { content: "v2" }));

    const block1 = useBlockStore.getState().blocks.get("block-1");
    const block2 = useBlockStore.getState().blocks.get("block-2");

    expect(block1?.props).toEqual({ content: "v2" });
    expect(block2?.props).toEqual({ data: [1] });
    expect(useBlockStore.getState().blocks.size).toBe(2);
  });

  it("replaceAllBlocks replaces all blocks and clears unrelated interactions", () => {
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("old-1"));
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("old-2"));
    useBlockStore.getState().setInteractionLoading("callback-stale");

    useBlockStore.getState().replaceAllBlocks("test-thread", [
      makeBlock("new-1"),
      makeBlock("new-2"),
    ]);

    const blocks = useBlockStore.getState().blocks;
    expect(blocks.size).toBe(2);
    expect(blocks.has("old-1")).toBe(false);
    expect(blocks.has("old-2")).toBe(false);
    expect(blocks.has("new-1")).toBe(true);
    expect(blocks.has("new-2")).toBe(true);
    expect(useBlockStore.getState().interactions.has("callback-stale")).toBe(false);
  });

  it("upsertBlock during streaming accumulates without replacing existing blocks", () => {
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("block-a", "text", { content: "A" }));
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("block-b", "text", { content: "B" }));
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("block-c", "text", { content: "C" }));

    const blocks = useBlockStore.getState().blocks;
    expect(blocks.size).toBe(3);
    expect(blocks.get("block-a")?.props.content).toBe("A");
    expect(blocks.get("block-b")?.props.content).toBe("B");
    expect(blocks.get("block-c")?.props.content).toBe("C");
  });

  it("full extraction (replaceAllBlocks) after streaming replaces all incremental blocks", () => {
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("stream-1", "text", { content: "streamed" }));
    useBlockStore.getState().upsertBlock("test-thread", makeBlock("stream-2", "chart", { data: [] }));

    const fullBlocks = [
      makeBlock("full-1", "text", { content: "full" }),
      makeBlock("stream-1", "text", { content: "full-updated" }),
    ];
    useBlockStore.getState().replaceAllBlocks("test-thread", fullBlocks);

    const blocks = useBlockStore.getState().blocks;
    expect(blocks.size).toBe(2);
    expect(blocks.has("stream-2")).toBe(false);
    expect(blocks.get("stream-1")?.props.content).toBe("full-updated");
    expect(blocks.get("full-1")?.props.content).toBe("full");
  });
});
