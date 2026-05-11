"use client";

import { useBlockStore } from "@/core/genui/store";

import { GenUIRenderer } from "./GenUIRenderer";

interface GenUIBlockListProps {
  threadId: string;
  onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
}

export function GenUIBlockList({ threadId: _threadId, onInteraction }: GenUIBlockListProps) {
  const blocks = useBlockStore((state) => state.blocks);

  const topLevelBlocks = Array.from(blocks.values()).filter(
    (block) => !block.parent_id,
  );

  if (topLevelBlocks.length === 0) {
    return null;
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {topLevelBlocks.map((block) => (
        <GenUIRenderer
          key={block.block_id}
          block={block}
          onInteraction={onInteraction}
        />
      ))}
    </div>
  );
}
