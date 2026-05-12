"use client";

import { useBlockStore } from "@/core/genui/store";

import { GenUIRenderer } from "./GenUIRenderer";

interface GenUIBlockListProps {
  threadId: string;
  blockIds?: string[];
  excludeBlockIds?: string[];
  disableExpiration?: boolean;
  onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
}

export function GenUIBlockList({ threadId: _threadId, blockIds, excludeBlockIds, disableExpiration, onInteraction }: GenUIBlockListProps) {
  const blocks = useBlockStore((state) => state.blocks);

  const filteredBlocks = Array.from(blocks.values()).filter((block) => {
    if (block.parent_id) return false;
    if (blockIds) return blockIds.includes(block.block_id);
    if (excludeBlockIds) return !excludeBlockIds.includes(block.block_id);
    return true;
  });

  if (filteredBlocks.length === 0) {
    return null;
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {filteredBlocks.map((block) => (
        <GenUIRenderer
          key={block.block_id}
          block={block}
          disableExpiration={disableExpiration}
          onInteraction={onInteraction}
        />
      ))}
    </div>
  );
}
