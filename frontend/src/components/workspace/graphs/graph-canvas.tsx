"use client";

/**
 * This file is kept as a minimal stub for backward compatibility.
 * Charts are now rendered inside the TipTap editor via ECharts.
 * See editor/chart-node-view.tsx for the actual chart rendering.
 */

export function GraphCanvas() {
  return (
    <div className="flex h-64 items-center justify-center rounded-lg border border-dashed text-muted-foreground">
      <p className="text-sm">
        Charts are now rendered within the dashboard editor.
      </p>
    </div>
  );
}
