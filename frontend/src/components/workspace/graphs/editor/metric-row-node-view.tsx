"use client";

import { type NodeViewProps, NodeViewWrapper } from "@tiptap/react";
import { useState, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

import { getDashboardTheme, subscribeDashboardTheme } from "../chart-themes";

interface MetricItem {
  metricId: string;
  label: string;
  value: string;
  change?: string;
}

function useTheme() {
  return useSyncExternalStore(subscribeDashboardTheme, getDashboardTheme, getDashboardTheme);
}

export function MetricRowNodeView({ node, selected, editor }: NodeViewProps) {
  const metrics: MetricItem[] = node.attrs.metrics ?? [];
  const [hovered, setHovered] = useState(false);
  const theme = useTheme();
  const accent = theme.colors[0] ?? "#2563eb";

  return (
    <NodeViewWrapper>
      <div
        className="group relative my-4"
        contentEditable={false}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Drag handle */}
        {editor.isEditable && (
          <div
            data-drag-handle
            draggable="true"
            className={cn(
              "absolute -left-8 top-1/2 z-10 -translate-y-1/2 cursor-grab rounded-md p-1 text-muted-foreground transition-opacity hover:bg-muted hover:text-foreground active:cursor-grabbing",
              hovered || selected ? "opacity-100" : "opacity-0",
            )}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="9" cy="5" r="1.5" />
              <circle cx="15" cy="5" r="1.5" />
              <circle cx="9" cy="12" r="1.5" />
              <circle cx="15" cy="12" r="1.5" />
              <circle cx="9" cy="19" r="1.5" />
              <circle cx="15" cy="19" r="1.5" />
            </svg>
          </div>
        )}
        <div
          className={cn(
            "grid gap-3",
            metrics.length <= 2
              ? "grid-cols-2"
              : metrics.length === 3
                ? "grid-cols-3"
                : "grid-cols-2 lg:grid-cols-4",
          )}
        >
          {metrics.map((metric: MetricItem, index: number) => (
            <div
              key={metric.metricId}
              className={cn(
                "relative overflow-hidden rounded-xl border p-4 transition-all duration-200",
                selected
                  ? "border-primary/40 shadow-[0_0_0_3px_rgba(37,99,235,0.1)]"
                  : "border-border/50 shadow-[0_1px_3px_0px_rgba(0,0,0,0.03)]",
              )}
              style={{ background: "linear-gradient(180deg, #ffffff 0%, #fafafa 100%)" }}
            >
              {/* Accent top bar */}
              <div
                className="absolute inset-x-0 top-0 h-[2px]"
                style={{
                  background: `linear-gradient(90deg, ${theme.colors[index % theme.colors.length]}80, ${theme.colors[(index + 1) % theme.colors.length]}40)`,
                }}
              />
              <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                {metric.label}
              </p>
              <p className="mt-1.5 text-2xl font-bold tracking-tight text-foreground">
                {metric.value}
              </p>
              {metric.change && (
                <div className="mt-1.5 flex items-center gap-1">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                      metric.change.startsWith("+")
                        ? "bg-emerald-50 text-emerald-600"
                        : metric.change.startsWith("-")
                          ? "bg-red-50 text-red-600"
                          : "bg-gray-50 text-muted-foreground",
                    )}
                  >
                    {metric.change.startsWith("+") && (
                      <svg className="mr-0.5 size-2.5" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M6 9V3M3 5l3-3 3 3" />
                      </svg>
                    )}
                    {metric.change.startsWith("-") && (
                      <svg className="mr-0.5 size-2.5" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M6 3v6M3 7l3 3 3-3" />
                      </svg>
                    )}
                    {metric.change}
                  </span>
                </div>
              )}
              {/* Subtle accent glow */}
              <div
                className="pointer-events-none absolute -bottom-4 -right-4 size-16 rounded-full opacity-[0.04] blur-2xl"
                style={{ backgroundColor: accent }}
              />
            </div>
          ))}
        </div>
      </div>
    </NodeViewWrapper>
  );
}
