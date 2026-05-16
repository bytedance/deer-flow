"use client";

import { useMemo } from "react";

import { useBlockStore } from "@/core/genui/store";
import { filterSupersededInteractiveBlockIds } from "@/core/genui/visibility";

import { GenUIRenderer } from "./GenUIRenderer";

interface GenUIBlockListProps {
  threadId: string;
  blockIds?: string[];
  excludeBlockIds?: string[];
  disableExpiration?: boolean;
  onInteraction?: (
    callbackId: string,
    payload: Record<string, unknown>,
    blockId?: string,
  ) => void;
}

export function GenUIBlockList({ threadId, blockIds, excludeBlockIds, disableExpiration, onInteraction }: GenUIBlockListProps) {
  const blocks = useBlockStore((state) => state.blocks);

  const filteredBlocks = useMemo(() => {
    const candidateBlocks = Array.from(blocks.values()).filter((block) => {
      if (block.parent_id) return false;
      if (blockIds) return blockIds.includes(block.block_id);
      if (excludeBlockIds) return !excludeBlockIds.includes(block.block_id);
      return true;
    });

    const visibleBlockIds = new Set(
      filterSupersededInteractiveBlockIds(
        candidateBlocks.map((block) => block.block_id),
        blocks,
      ),
    );

    return candidateBlocks
      .filter((block) => visibleBlockIds.has(block.block_id))
      .sort((a, b) => (a.sequence ?? Infinity) - (b.sequence ?? Infinity));
  }, [blockIds, blocks, excludeBlockIds]);

  if (filteredBlocks.length === 0) {
    return null;
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {filteredBlocks.map((block) => (
        <GenUIRenderer
          key={block.block_id}
          block={block}
          threadId={threadId}
          disableExpiration={disableExpiration}
          onInteraction={onInteraction}
        />
      ))}
    </div>
  );
}
