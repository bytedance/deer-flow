"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { cn } from "@/lib/utils";

import type { CanvasNode, PythonScriptNodeData } from "@/core/canvas/types";

export function PythonScriptNode({ data, selected }: NodeProps<CanvasNode>) {
  const nodeData = data as PythonScriptNodeData;

  return (
    <div
      className={cn(
        "min-w-[150px] rounded-md border bg-card p-3 shadow-sm",
        selected && "ring-2 ring-primary",
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-primary" />
      <div className="text-sm font-medium">Python Script</div>
      <div className="mt-1 text-xs text-muted-foreground">
        {nodeData.script_name ?? "Untitled"}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-primary" />
    </div>
  );
}