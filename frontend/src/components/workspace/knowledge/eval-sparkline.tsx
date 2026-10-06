/**
 * Tile sparkline (spec 2026-09-06 §5, plan Task 3).
 *
 * A pure-SVG mini trend line for the 7 Layer-2 metric tiles — no echarts, so it
 * renders (and is testable) under jsdom. The fixed 28×12 footprint (w-7 h-3) sits
 * on the tile's value row, right of the number. Neutral muted-foreground stroke via
 * currentColor (no 11th color vocabulary); a min–max normalized polyline plus a
 * solid dot on the latest point. Returns null when there are fewer than two values
 * (nothing to draw a trend from), so an all-null / absent series leaves the value
 * row exactly as before. Scanning only — no interaction; drill-down goes through
 * the picker/drawer.
 *
 * `className` 透传到 svg（2026-09-07 窄栏溢出治理）：瓦片经容器查询按档隐线
 * （hidden + @min-[…]），本组件不自带任何响应式决策。
 */

import { cn } from "@/lib/utils";

const SPARK_W = 28;
const SPARK_H = 12;
/** Inset so the 1.5px stroke and the end dot are not clipped at the viewBox edges. */
const SPARK_PAD = 1.5;

const round2 = (n: number): number => Math.round(n * 100) / 100;

export function EvalSparkline({ values, className }: { values?: number[] | null; className?: string }) {
  if (!values || values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const innerW = SPARK_W - SPARK_PAD * 2;
  const innerH = SPARK_H - SPARK_PAD * 2;
  const lastIndex = values.length - 1;

  // min→bottom, max→top so the trend shape fills the 12px height; a flat series
  // (span=0) sits at mid-height instead of dividing by zero.
  const pts = values.map((v, i) => {
    const x = SPARK_PAD + (i / lastIndex) * innerW;
    const y = span === 0 ? SPARK_PAD + innerH / 2 : SPARK_PAD + innerH - ((v - min) / span) * innerH;
    return { x: round2(x), y: round2(y) };
  });
  const end = pts[lastIndex]!;

  return (
    <svg aria-hidden="true" className={cn("text-muted-foreground h-3 w-7 shrink-0", className)} viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} fill="none">
      <polyline points={pts.map((p) => `${p.x},${p.y}`).join(" ")} stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <circle cx={end.x} cy={end.y} r={1.5} fill="currentColor" />
    </svg>
  );
}
