"use client";

import { useMemo } from "react";

import { useBlockStore, type UIBlock } from "@/core/genui/store";

import { GenUIRenderer } from "./GenUIRenderer";

interface LayoutBlockProps {
  block: UIBlock;
  threadId?: string;
}

export default function LayoutBlock({ block, threadId }: LayoutBlockProps) {
  const { props, block_id } = block;
  const { layout_type, columns = 2, gap = 16, align = "stretch" } = props as {
    layout_type?: string;
    columns?: number;
    gap?: number;
    align?: string;
  };

  const blocks = useBlockStore((state) => state.blocks);
  const children = useMemo(
    () => Array.from(blocks.values()).filter((b) => b.parent_id === block_id && b.thread_id === block.thread_id),
    [blocks, block_id, block.thread_id],
  );

  const style: React.CSSProperties =
    layout_type === "grid"
      ? {
          display: "grid",
          gridTemplateColumns: `repeat(${columns}, 1fr)`,
          gap: `${gap}px`,
          alignItems: align,
        }
      : {
          display: "flex",
          flexWrap: "wrap",
          gap: `${gap}px`,
          alignItems: align,
        };

  return (
    <div style={style} role="group" aria-label={`${layout_type} layout`}>
      {children.map((child) => (
        <GenUIRenderer key={child.block_id} block={child} threadId={threadId} />
      ))}
    </div>
  );
}
