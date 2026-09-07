"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { AgentThread } from "@/core/threads/types";

const VIRTUALIZATION_THRESHOLD = 60;

export function calculateScrollMargin(
  rootTop: number,
  scrollParentTop: number,
  scrollTop: number,
) {
  return Math.max(0, rootTop - scrollParentTop + scrollTop);
}

export function VirtualThreadList({
  estimateSize,
  gap = 0,
  items,
  renderItem,
  scrollParentSelector,
}: {
  estimateSize: number;
  gap?: number;
  items: readonly AgentThread[];
  renderItem: (thread: AgentThread, index: number) => ReactNode;
  scrollParentSelector: string;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const getScrollElement = useCallback(
    () => rootRef.current?.closest<HTMLElement>(scrollParentSelector) ?? null,
    [scrollParentSelector],
  );
  const [scrollMargin, setScrollMargin] = useState(0);
  useLayoutEffect(() => {
    const root = rootRef.current;
    const scrollParent = getScrollElement();
    if (!root || !scrollParent) return;
    const measure = () => {
      setScrollMargin(
        calculateScrollMargin(
          root.getBoundingClientRect().top,
          scrollParent.getBoundingClientRect().top,
          scrollParent.scrollTop,
        ),
      );
    };
    measure();
    // Sidebar sections above the list (project groups, archived section)
    // resize without changing items.length, shifting the list's offset.
    // Observe the scroll parent and its children so the margin is
    // recomputed whenever any of them changes size.
    const observer = new ResizeObserver(measure);
    observer.observe(scrollParent);
    for (const child of scrollParent.children) {
      observer.observe(child);
    }
    return () => observer.disconnect();
  }, [getScrollElement, items.length]);
  const virtualizer = useVirtualizer({
    count: items.length,
    estimateSize: () => estimateSize,
    getItemKey: (index) => items[index]?.thread_id ?? index,
    getScrollElement,
    overscan: 8,
    scrollMargin,
  });

  if (items.length < VIRTUALIZATION_THRESHOLD) {
    return (
      <div
        ref={rootRef}
        className="flex w-full flex-col"
        style={{ gap: `${gap}px` }}
      >
        {items.map(renderItem)}
      </div>
    );
  }

  return (
    <div
      ref={rootRef}
      className="relative w-full"
      style={{ height: `${virtualizer.getTotalSize()}px` }}
    >
      {virtualizer.getVirtualItems().map((virtualRow) => {
        const thread = items[virtualRow.index];
        if (!thread) return null;
        return (
          <div
            key={virtualRow.key}
            ref={virtualizer.measureElement}
            data-index={virtualRow.index}
            className="absolute top-0 left-0 w-full"
            style={{
              paddingBottom: `${gap}px`,
              transform: `translateY(${virtualRow.start - scrollMargin}px)`,
            }}
          >
            {renderItem(thread, virtualRow.index)}
          </div>
        );
      })}
    </div>
  );
}
