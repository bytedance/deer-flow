"use client";

import {
  defaultRangeExtractor,
  useVirtualizer,
  type Range,
} from "@tanstack/react-virtual";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  type Key,
  type ReactNode,
} from "react";
import { useStickToBottomContext } from "use-stick-to-bottom";

import type { MessageGroup } from "@/core/messages/utils";

const VIRTUALIZATION_THRESHOLD = 60;
const ESTIMATED_ROW_HEIGHT = 176;
const GROUP_START_OFFSET = 16;
const VIRTUAL_SCROLL_SETTLE_ATTEMPTS = 4;
const STATIC_SCROLL_SETTLE_ATTEMPTS = 2;

type GroupAlignment = "start" | "center";

type ScrollToGroupOptions = {
  behavior?: ScrollBehavior;
  align?: GroupAlignment;
};

type VirtualMessageListProps = {
  groups: readonly MessageGroup[];
  isLoading: boolean;
  renderGroup: (group: MessageGroup, index: number) => ReactNode;
  onActiveGroupChange?: (groupIndex: number) => void;
};

export type VirtualMessageListHandle = {
  scrollToGroup: (groupIndex: number, options?: ScrollToGroupOptions) => void;
};

function groupKey(group: MessageGroup | undefined, index: number): Key {
  return (
    group?.id ??
    group?.messages.find((message) => message.id)?.id ??
    `${group?.type ?? "message"}:${index}`
  );
}

export const VirtualMessageList = forwardRef<
  VirtualMessageListHandle,
  VirtualMessageListProps
>(function VirtualMessageList(
  { groups, isLoading, renderGroup, onActiveGroupChange },
  ref,
) {
  const { isAtBottom, scrollRef, scrollToBottom, stopScroll } =
    useStickToBottomContext();
  const listRef = useRef<HTMLDivElement | null>(null);
  const activeIndex = isLoading ? groups.length - 1 : -1;
  const getItemKey = useCallback(
    (index: number) => groupKey(groups[index], index),
    [groups],
  );
  const rangeExtractor = useCallback(
    (range: Range) => {
      const indices = defaultRangeExtractor(range);
      if (activeIndex >= 0 && !indices.includes(activeIndex)) {
        indices.push(activeIndex);
        indices.sort((a, b) => a - b);
      }
      return indices;
    },
    [activeIndex],
  );
  const virtualizer = useVirtualizer({
    count: groups.length,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    getItemKey,
    getScrollElement: () => scrollRef.current,
    overscan: 8,
    rangeExtractor,
  });
  const virtualItems = virtualizer.getVirtualItems();
  const shouldVirtualize = groups.length >= VIRTUALIZATION_THRESHOLD;
  const firstVirtualIndex = virtualItems[0]?.index ?? -1;
  const lastVirtualIndex = virtualItems.at(-1)?.index ?? -1;
  const positionedInitialVirtualWindowRef = useRef(false);
  const previousCountRef = useRef(groups.length);
  const previousFirstKeyRef = useRef<Key | undefined>(undefined);
  const previousActiveGroupRef = useRef(-1);
  const anchorRef = useRef<{ key: Key; viewportOffset: number } | undefined>(
    undefined,
  );

  const alignGroupToViewport = useCallback(
    (
      groupIndex: number,
      align: GroupAlignment,
      behavior: ScrollBehavior,
    ): boolean => {
      const viewport = scrollRef.current;
      const row = listRef.current?.querySelector<HTMLElement>(
        `[data-message-group-index="${groupIndex}"]`,
      );
      if (!viewport || !row) {
        return false;
      }

      const viewportRect = viewport.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      const top =
        viewport.scrollTop +
        rowRect.top -
        viewportRect.top -
        (align === "center"
          ? Math.max(0, (viewport.clientHeight - rowRect.height) / 2)
          : GROUP_START_OFFSET);
      viewport.scrollTo({ top: Math.max(0, top), behavior });
      return true;
    },
    [scrollRef],
  );

  useImperativeHandle(
    ref,
    () => ({
      scrollToGroup(groupIndex, options) {
        if (groupIndex < 0 || groupIndex >= groups.length) {
          return;
        }
        stopScroll();
        const behavior = options?.behavior ?? "auto";
        const align = options?.align ?? "start";
        if (shouldVirtualize) {
          virtualizer.scrollToIndex(groupIndex, { align, behavior });
        }

        const maxAttempts = shouldVirtualize
          ? VIRTUAL_SCROLL_SETTLE_ATTEMPTS
          : STATIC_SCROLL_SETTLE_ATTEMPTS;
        let attempt = 0;
        const settleOnExactGroup = () => {
          const exactBehavior = attempt === 0 ? behavior : "auto";
          const aligned = alignGroupToViewport(
            groupIndex,
            align,
            exactBehavior,
          );
          attempt += 1;
          const needsAnotherAttempt = shouldVirtualize || !aligned;
          if (attempt < maxAttempts && needsAnotherAttempt) {
            requestAnimationFrame(settleOnExactGroup);
          }
        };
        requestAnimationFrame(settleOnExactGroup);
      },
    }),
    [
      alignGroupToViewport,
      groups.length,
      shouldVirtualize,
      stopScroll,
      virtualizer,
    ],
  );

  useEffect(() => {
    const viewport = scrollRef.current;
    const list = listRef.current;
    if (!viewport || !list || !onActiveGroupChange) {
      return;
    }

    let animationFrame: number | undefined;
    const updateActiveGroup = () => {
      animationFrame = undefined;
      const rows = list.querySelectorAll<HTMLElement>(
        "[data-message-group-index]",
      );
      if (rows.length === 0) {
        return;
      }

      const readingLine = viewport.getBoundingClientRect().top + 96;
      let activeRow = rows[0];
      for (const row of rows) {
        if (row.getBoundingClientRect().top > readingLine) {
          break;
        }
        activeRow = row;
      }
      const groupIndex = Number(activeRow?.dataset.messageGroupIndex);
      if (
        Number.isSafeInteger(groupIndex) &&
        groupIndex !== previousActiveGroupRef.current
      ) {
        previousActiveGroupRef.current = groupIndex;
        onActiveGroupChange(groupIndex);
      }
    };
    const scheduleUpdate = () => {
      animationFrame ??= requestAnimationFrame(updateActiveGroup);
    };

    scheduleUpdate();
    viewport.addEventListener("scroll", scheduleUpdate, { passive: true });
    return () => {
      viewport.removeEventListener("scroll", scheduleUpdate);
      if (animationFrame !== undefined) {
        cancelAnimationFrame(animationFrame);
      }
    };
  }, [
    firstVirtualIndex,
    groups,
    lastVirtualIndex,
    onActiveGroupChange,
    scrollRef,
  ]);

  useLayoutEffect(() => {
    let settleFrame: number | undefined;
    if (
      shouldVirtualize &&
      isAtBottom &&
      !positionedInitialVirtualWindowRef.current
    ) {
      positionedInitialVirtualWindowRef.current = true;
      const scrollToLatest = () => {
        virtualizer.scrollToIndex(groups.length - 1, { align: "end" });
      };
      scrollToLatest();
      // Dynamic row measurement changes the total after the first layout.
      // Re-anchor once with measured sizes so a long restored conversation
      // cannot land around the estimated midpoint.
      settleFrame = requestAnimationFrame(scrollToLatest);
    } else if (!shouldVirtualize) {
      positionedInitialVirtualWindowRef.current = false;
    }
    if (groups.length > previousCountRef.current && isAtBottom) {
      void scrollToBottom({
        animation: "instant",
        preserveScrollPosition: true,
      });
    }
    previousCountRef.current = groups.length;
    return () => {
      if (settleFrame !== undefined) cancelAnimationFrame(settleFrame);
    };
  }, [
    groups.length,
    isAtBottom,
    scrollToBottom,
    shouldVirtualize,
    virtualizer,
  ]);

  useLayoutEffect(() => {
    const firstKey = getItemKey(0);
    const previousFirstKey = previousFirstKeyRef.current;
    const anchor = anchorRef.current;
    if (
      previousFirstKey !== undefined &&
      firstKey !== previousFirstKey &&
      anchor
    ) {
      const anchorIndex = groups.findIndex(
        (group, index) => groupKey(group, index) === anchor.key,
      );
      if (anchorIndex >= 0) {
        const anchorStart = virtualizer.getOffsetForIndex(
          anchorIndex,
          "start",
        )?.[0];
        if (anchorStart !== undefined) {
          virtualizer.scrollToOffset(anchorStart - anchor.viewportOffset, {
            behavior: "auto",
          });
        }
      }
    }
    previousFirstKeyRef.current = firstKey;

    const scrollOffset = virtualizer.scrollOffset ?? 0;
    const firstVisible = virtualItems.find((item) => item.end >= scrollOffset);
    if (firstVisible) {
      anchorRef.current = {
        key: firstVisible.key,
        viewportOffset: firstVisible.start - scrollOffset,
      };
    }
  }, [getItemKey, groups, virtualItems, virtualizer]);

  if (!shouldVirtualize) {
    return (
      <div ref={listRef} className="flex flex-col gap-8">
        {groups.map((group, index) => (
          <div key={getItemKey(index)} data-message-group-index={index}>
            {renderGroup(group, index)}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div
      ref={listRef}
      className="relative w-full"
      style={{ height: `${virtualizer.getTotalSize()}px` }}
    >
      {virtualItems.map((virtualRow) => {
        const group = groups[virtualRow.index];
        if (!group) return null;
        return (
          <div
            key={virtualRow.key}
            ref={virtualizer.measureElement}
            data-index={virtualRow.index}
            data-message-group-index={virtualRow.index}
            className="absolute top-0 left-0 w-full pb-8"
            style={{ transform: `translateY(${virtualRow.start}px)` }}
          >
            {renderGroup(group, virtualRow.index)}
          </div>
        );
      })}
    </div>
  );
});
