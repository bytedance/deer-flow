"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { cn } from "@/lib/utils";

import type { CanvasNode, DataSourceNodeData } from "@/core/canvas/types";

export function DataSourceNode({ data, selected }: NodeProps<CanvasNode>) {
  const nodeData = data as DataSourceNodeData;

  return (
    <div
      className={cn(
        "min-w-[150px] rounded-md border bg-card p-3 shadow-sm",
        selected && "ring-2 ring-primary",
      )}
    >
      <div className="text-sm font-medium">Data Source</div>
      <div className="mt-1 text-xs text-muted-foreground">
        {nodeData.table_name ?? "Untitled"}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-primary" />
    </div>
  );
}