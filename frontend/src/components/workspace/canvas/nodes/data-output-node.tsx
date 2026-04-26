"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { CanvasNode, DataOutputNodeData } from "@/core/canvas/types";
import { cn } from "@/lib/utils";

export function DataOutputNode({ data, selected }: NodeProps<CanvasNode>) {
  const nodeData = data as DataOutputNodeData;

  return (
    <div
      className={cn(
        "min-w-[150px] rounded-md border bg-card p-3 shadow-sm",
        selected && "ring-2 ring-primary",
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-primary" />
      <div className="text-sm font-medium">Data Output</div>
      <div className="mt-1 text-xs text-muted-foreground">
        {nodeData.output_name ?? "Untitled"}
      </div>
    </div>
  );
}