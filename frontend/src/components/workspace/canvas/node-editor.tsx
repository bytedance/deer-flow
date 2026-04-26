"use client";

import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { useCanvasContext } from "./context";

export function NodeEditor() {
  const { selectedNodeId, canvas, setIsEditing } = useCanvasContext();

  const selectedNode = canvas?.nodes.find((n) => n.id === selectedNodeId);

  if (!selectedNode) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Select a node to edit
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-medium">Edit Node</h3>
        <Button variant="ghost" size="icon" onClick={() => setIsEditing(false)}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="space-y-4">
        <div>
          <Label>Node ID</Label>
          <Input value={selectedNode.id} disabled />
        </div>
        <div>
          <Label>Type</Label>
          <Input value={selectedNode.type ?? "unknown"} disabled />
        </div>
        {/* Add more fields based on node type */}
      </div>
    </div>
  );
}
