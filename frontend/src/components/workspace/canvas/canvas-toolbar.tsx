"use client";

import { Play, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

import { useCanvasContext } from "./context";

interface CanvasToolbarProps {
  onExecute?: () => void;
  onSave?: () => void;
  onDelete?: () => void;
  isExecuting?: boolean;
}

export function CanvasToolbar({ onExecute, onSave, onDelete, isExecuting }: CanvasToolbarProps) {
  const { canvas } = useCanvasContext();

  return (
    <div className="flex items-center gap-2 border-b bg-background px-4 py-2">
      <span className="text-sm font-medium">{canvas?.name ?? "Canvas"}</span>
      <Separator orientation="vertical" className="h-6" />
      <Button
        variant="outline"
        size="sm"
        onClick={onExecute}
        disabled={!canvas || canvas.nodes.length === 0 || isExecuting}
      >
        <Play className="mr-1 h-4 w-4" />
        Execute
      </Button>
      <Button variant="outline" size="sm" onClick={onSave}>
        <Save className="mr-1 h-4 w-4" />
        Save
      </Button>
      <Separator orientation="vertical" className="h-6" />
      <Button variant="ghost" size="sm" onClick={onDelete}>
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}
