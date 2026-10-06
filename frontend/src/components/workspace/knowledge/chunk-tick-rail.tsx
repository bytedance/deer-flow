"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

/** 可见刻度槽数（奇数 → active 居中）；弹窗可见行数同值（行与刻度一一对应）。 */
const VISIBLE_TICKS = 11;
/** 刻度间距 == 弹窗行高（2026-09-05 二改）：刻度是主体，悬浮前后几何恒定，
    弹窗只是贴在刻度左侧的标签层，行槽与刻度槽逐一对齐。34px 也回应了
    “刻度太密”的反馈。 */
const TICK_GAP = 34;
/** 刻度按钮热区高度（小于间距，热区之间留隙不粘连）。 */
const TICK_HIT = 16;

/**
 * Clamped render window of tick indices around `active` (pure → unit tested).
 * Always stays inside [0, total) and keeps at least one visible band of ticks
 * at the document edges so the masked column never shows an empty half.
 */
export function tickRange(active: number, total: number, radius = 10): { end: number; start: number } {
  if (total <= 0) return { end: 0, start: 0 };
  const a = Math.min(Math.max(active, 0), total - 1);
  const r = Math.max(radius, Math.floor(VISIBLE_TICKS / 2));
  const start = Math.max(0, Math.min(a - r, total - 1));
  const end = Math.min(total, Math.max(a + r + 1, start + Math.min(total, VISIBLE_TICKS)));
  return { end, start };
}

export interface ChunkTickEntry {
  index: number;
  preview: string | null;
}

/**
 * Kimi-style chunk minimap (2026-09-05 切片导航): the tick spine is the subject —
 * a windowed tick column at the drawer's right edge whose geometry (x, size,
 * gap) is identical in both states. Hovering opens a label panel to the LEFT
 * of the spine: its rows are exactly TICK_GAP tall so each row aligns 1:1 with
 * a tick, and scrolling the panel drives the same shared tick window (ticks
 * slide with it). Clicking a tick or row jumps the drawer to that chunk.
 * Overlay layer: never part of the drawer's scroll flow.
 */
export function ChunkTickRail({
  total,
  active,
  entries,
  onJump,
  tickLabel,
  unloadedLabel,
}: {
  total: number;
  active: number;
  /** Loaded chunks in list order (popup rows beyond them render greyed). */
  entries: ChunkTickEntry[];
  onJump: (index: number) => void;
  /** Aria prefix, e.g. "切片" / "Chunk". */
  tickLabel: string;
  unloadedLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const popupScrollRef = useRef<HTMLDivElement | null>(null);

  const clearTimers = () => {
    if (openTimer.current) clearTimeout(openTimer.current);
    if (closeTimer.current) clearTimeout(closeTimer.current);
  };
  // Hover intent: entering the rail opens the popup after a beat; leaving
  // rail *and* popup closes it (the grace lets the pointer travel across).
  const scheduleOpen = () => {
    clearTimers();
    openTimer.current = setTimeout(() => setOpen(true), 150);
  };
  const scheduleClose = () => {
    clearTimers();
    closeTimer.current = setTimeout(() => setOpen(false), 200);
  };
  useEffect(() => clearTimers, []);

  const previews = useMemo(() => new Map(entries.map((entry) => [entry.index, entry.preview])), [entries]);
  const clampedActive = total > 0 ? Math.min(Math.max(active, 0), total - 1) : 0;

  // 共享窗口偏移（可为小数行）：弹窗打开时由其 scrollTop 驱动；收起时让
  // active 居中。两种状态共用同一套刻度定位公式 → 几何恒定。
  const maxOffset = Math.max(0, total - VISIBLE_TICKS);
  const offset = open
    ? Math.min(scrollTop / TICK_GAP, maxOffset)
    : Math.min(Math.max(clampedActive - (VISIBLE_TICKS - 1) / 2, 0), maxOffset);
  const base = Math.floor(offset);
  const frac = offset - base;
  const { start, end } = tickRange(base + (VISIBLE_TICKS - 1) / 2, total);
  const ticks = useMemo(() => Array.from({ length: end - start }, (_, i) => start + i), [start, end]);

  // 打开时把 active 行滚到弹窗可见带中心；scroll 事件随后同步 offset。
  useEffect(() => {
    if (!open) return;
    const vp = popupScrollRef.current;
    if (!vp) return;
    const max = Math.max(0, vp.scrollHeight - vp.clientHeight);
    vp.scrollTop = Math.min(Math.max((clampedActive - (VISIBLE_TICKS - 1) / 2) * TICK_GAP, 0), max);
    setScrollTop(vp.scrollTop);
  }, [open, clampedActive]);

  // 弹窗滚动 → 共享窗口偏移（rAF 节流）。
  useEffect(() => {
    const vp = popupScrollRef.current;
    if (!open || !vp) return;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        setScrollTop(vp.scrollTop);
      });
    };
    vp.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      vp.removeEventListener("scroll", onScroll);
    };
  }, [open]);

  if (total <= 1) return null;

  const bandHeight = Math.min(total, VISIBLE_TICKS) * TICK_GAP;

  return (
    <div
      className="pointer-events-none absolute inset-y-0 right-1 z-10 flex w-10 items-center justify-end"
      onMouseEnter={scheduleOpen}
      onMouseLeave={scheduleClose}
    >
      {/* 标签层：行高 == TICK_GAP，行槽与刻度槽逐一对齐；其滚动驱动共享窗口。
          右缘 pr-8 给刻度列与弹窗滚动条让位。 */}
      {open && (
        <div
          className="bg-popover text-popover-foreground pointer-events-auto absolute right-0 top-1/2 z-10 w-72 -translate-y-1/2 rounded-xl border shadow-lg"
          style={{ height: bandHeight }}
        >
          <ScrollArea className="size-full" viewportRef={popupScrollRef}>
            {/* p-1：跳转行全宽贴视口会把外扩 3px 的 focus ring 切掉，行盒内缩 4px 给环让位 */}
            <div className="flex flex-col p-1">
              {Array.from({ length: total }, (_, index) => {
                const preview = previews.get(index) ?? null;
                const isActive = index === clampedActive;
                return (
                  <button
                    className={cn(
                      "flex items-center gap-2 pr-8 pl-2 text-left text-xs",
                      isActive ? "bg-accent/60 text-foreground" : "text-muted-foreground hover:bg-accent/40",
                    )}
                    key={index}
                    onClick={() => {
                      onJump(index);
                      setOpen(false);
                    }}
                    style={{ height: TICK_GAP }}
                    type="button"
                  >
                    <span className="w-8 shrink-0 text-right font-mono tabular-nums opacity-70">#{index + 1}</span>
                    <span className={cn("min-w-0 flex-1 truncate", !preview && "italic opacity-70")}>
                      {preview ?? unloadedLabel}
                    </span>
                  </button>
                );
              })}
            </div>
          </ScrollArea>
        </div>
      )}
      {/* 刻度主体：两种状态同一公式定位（(index-base)*gap - frac*gap），
          x/尺寸/间距恒不变化；overflow + mask 截断窗口外刻度。z-20 压在标签层上。 */}
      <div
        className="pointer-events-auto relative z-20 w-6 overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_20%,black_80%,transparent)]"
        style={{ height: bandHeight }}
      >
        {ticks.map((index) => (
          <button
            aria-label={`${tickLabel} #${index + 1}`}
            className="absolute right-1 flex w-4 cursor-pointer items-center justify-end"
            key={index}
            onClick={() => onJump(index)}
            style={{
              top: (index - base) * TICK_GAP - frac * TICK_GAP + (TICK_GAP - TICK_HIT) / 2,
              height: TICK_HIT,
              transition: "top 180ms ease",
            }}
            type="button"
          >
            <span
              className={cn(
                "h-0.5 rounded-full transition-all",
                index === clampedActive ? "w-3.5 bg-foreground/80" : "hover:bg-foreground/50 w-2.5 bg-foreground/30",
              )}
            />
          </button>
        ))}
      </div>
    </div>
  );
}
