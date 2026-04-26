"use client";

import { CheckCircle, XCircle, Loader2, Clock } from "lucide-react";

import type { ExecutionStatusResponse, CanvasStatus } from "@/core/canvas/types";

interface ExecutionStatusProps {
  status: ExecutionStatusResponse | null;
  isLoading?: boolean;
}

const statusIcons: Record<CanvasStatus, React.ReactNode> = {
  idle: <Clock className="h-4 w-4" />,
  running: <Loader2 className="h-4 w-4 animate-spin" />,
  paused: <Clock className="h-4 w-4" />,
  completed: <CheckCircle className="h-4 w-4 text-green-500" />,
  failed: <XCircle className="h-4 w-4 text-red-500" />,
};

export function ExecutionStatus({ status }: ExecutionStatusProps) {
  if (!status) return null;

  return (
    <div className="border-t bg-background p-4">
      <div className="flex items-center gap-2">
        {statusIcons[status.status]}
        <span className="text-sm font-medium capitalize">{status.status}</span>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        Completed: {status.completed_nodes.length} / Pending: {status.pending_nodes.length}
      </div>
    </div>
  );
}
