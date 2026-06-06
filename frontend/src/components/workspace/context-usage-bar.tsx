"use client";

import { useMemo } from "react";

import type { ContextUsageBreakdownItem } from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

export interface ContextUsageBarSegment {
  key: string;
  /** Fractional share of the total window (0..1). */
  ratio: number;
  /** Tooltip label rendered on hover. */
  label: string;
  /** Whether the segment counts toward "used" — controls coloring. */
  active: boolean;
}

interface ContextUsageBarProps {
  segments: ContextUsageBarSegment[];
  className?: string;
}

/**
 * Multi-segment progress bar mirroring the layout of Claude Code's context
 * window indicator: solid color for active categories, muted tones for
 * reserved (deferred / autocompact buffer / free space).
 *
 * Segments are positioned absolutely so a zero-width segment renders as
 * nothing rather than a thin sliver that might collect rounding error.
 */
export function ContextUsageBar({ segments, className }: ContextUsageBarProps) {
  const positioned = useMemo(() => {
    let cursor = 0;
    return segments
      .filter((seg) => seg.ratio > 0)
      .map((seg) => {
        const start = cursor;
        cursor = Math.min(1, cursor + seg.ratio);
        return { ...seg, start, end: cursor };
      });
  }, [segments]);

  return (
    <div
      className={cn(
        "bg-muted/40 relative h-2 w-full overflow-hidden rounded-full",
        className,
      )}
      role="presentation"
    >
      {positioned.map((seg) => (
        <div
          key={seg.key}
          title={seg.label}
          aria-label={seg.label}
          className={cn(
            "absolute top-0 bottom-0",
            seg.active
              ? "bg-primary/80 hover:bg-primary"
              : "bg-muted-foreground/30 hover:bg-muted-foreground/40",
          )}
          style={{
            left: `${seg.start * 100}%`,
            width: `${Math.max(0, seg.end - seg.start) * 100}%`,
          }}
        />
      ))}
    </div>
  );
}

/**
 * Convert a breakdown list into bar segments. When the window is unknown the
 * ratio is computed against the sum of the breakdown rows, so the bar still
 * conveys relative shares even without a denominator.
 */
export function breakdownToSegments(
  breakdown: ContextUsageBreakdownItem[],
  maxContextTokens: number | null,
  labeller: (item: ContextUsageBreakdownItem) => string,
): ContextUsageBarSegment[] {
  if (breakdown.length === 0) {
    return [];
  }
  const denominator =
    maxContextTokens && maxContextTokens > 0
      ? maxContextTokens
      : breakdown.reduce((sum, row) => sum + row.tokens, 0);
  if (denominator <= 0) {
    return [];
  }
  return breakdown.map((row) => ({
    key: row.key,
    ratio: row.tokens / denominator,
    label: labeller(row),
    active: row.active,
  }));
}
