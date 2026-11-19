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
  useMemo,
  useRef,
  useState,
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
const PIN_SETTLE_FRAMES = 5;

type GroupAlignment = "start" | "center";

type ScrollToGroupOptions = {
  behavior?: ScrollBehavior;
  align?: GroupAlignment;
};

type VirtualMessageListProps = {
  groups: readonly MessageGroup[];
  isLoading: boolean;
  renderGroup: (group: MessageGroup, index: number) => ReactNode;
  /**
   * Extra content rendered after a group inside its row (e.g. schedule event
   * lines at the end of a turn), so it is measured and scrolled with it.
   */
  renderAfterGroup?: (index: number) => ReactNode;
  onActiveGroupChange?: (groupIndex: number) => void;
  /**
   * Key of a freshly sent user group to pin to the top of the viewport
   * (ChatGPT-style send behavior). Keyed, not indexed: history pagination
   * prepends groups and would shift an index. While set, a flexible spacer
   * grows at the end of the list so the pinned row can actually reach the
   * top — it is the last row, so without the spacer the browser clamps the
   * scroll — and the spacer shrinks as the streamed reply grows beneath it.
   * `null` clears it.
   */
  pinGroupKey?: string | null;
};

export type VirtualMessageListHandle = {
  scrollToGroup: (groupIndex: number, options?: ScrollToGroupOptions) => void;
  /**
   * Hands scroll control back to the user immediately: cancels a running
   * send-pin chain (escape ticks and settle frames) without clearing the
   * pin itself. Wired to explicit user intents that do not originate as
   * input on the scroll element, e.g. the scroll-to-bottom button.
   */
  cancelPinFollow: () => void;
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
  {
    groups,
    isLoading,
    renderGroup,
    renderAfterGroup,
    onActiveGroupChange,
    pinGroupKey,
  },
  ref,
) {
  const { isAtBottom, scrollRef, scrollToBottom, stopScroll } =
    useStickToBottomContext();
  const listRef = useRef<HTMLDivElement | null>(null);
  const [pinSpacerHeight, setPinSpacerHeight] = useState(0);
  const pinSpacerHeightRef = useRef(0);
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

  const pinnedIndex = useMemo(() => {
    if (pinGroupKey == null) {
      return null;
    }
    const index = groups.findIndex(
      (_, groupIndex) => String(getItemKey(groupIndex)) === pinGroupKey,
    );
    return index >= 0 ? index : null;
  }, [getItemKey, groups, pinGroupKey]);

  const updatePinSpacer = useCallback(() => {
    const viewport = scrollRef.current;
    if (pinnedIndex == null || !viewport) {
      return;
    }
    const row = listRef.current?.querySelector<HTMLElement>(
      `[data-message-group-index="${pinnedIndex}"]`,
    );
    if (!row) {
      return;
    }
    const rowRect = row.getBoundingClientRect();
    // Everything after the pinned row, excluding this spacer itself and the
    // row's own height: the spacer must make up whatever is missing so the
    // row can still reach the top of the viewport.
    const afterContent = Math.max(
      0,
      viewport.scrollHeight -
        pinSpacerHeightRef.current -
        (rowRect.bottom + viewport.scrollTop),
    );
    const needed = Math.max(
      0,
      viewport.clientHeight -
        rowRect.height -
        GROUP_START_OFFSET -
        afterContent,
    );
    pinSpacerHeightRef.current = needed;
    setPinSpacerHeight((previous) => (previous === needed ? previous : needed));
  }, [pinnedIndex, scrollRef]);

  // Runs the pin chain once per pin key: frame one sizes the spacer, frame
  // two aligns, then a few settle frames re-align (the virtualized branch
  // re-measures rows after the alignment). The whole chain — rAF ids and
  // escape timeouts — lives in a ref and is NOT cancelled by this effect's
  // cleanup: groups churn on every stream chunk, and a chunk landing between
  // the frames would otherwise cancel the pending alignment mid-chain and
  // restart it against already-grown geometry (the spacer computes to 0 and
  // the pin collapses). Only clearing the pin or unmount cancels.
  //
  // The spacer is sized once and stays frozen for the run: re-measuring per
  // chunk would shrink it in lockstep with the reply, and the net-negative
  // resize makes use-stick-to-bottom re-lock its follow while the bottom gap
  // is still inside its 70px band — after which every chunk drags the
  // viewport down without user input. A frozen spacer keeps each chunk a
  // net-positive resize (the follow stays escaped), and an explicit user
  // scroll down re-locks normally through scroll events. The spacer
  // collapses when the pin clears.
  const pinChainKeyRef = useRef<string | null>(null);
  const pinFramesRef = useRef<number[]>([]);
  const pinEscapeTimersRef = useRef<number[]>([]);
  // User-intent listeners, attached for the chain's lifetime: `wheel`,
  // `touchstart` and `pointerdown` never fire for programmatic `scrollTo`, so
  // they distinguish real scrolling (wheel/trackpad/touch, scrollbar and
  // selection drags) from the resize-animation churn the chain defends
  // against. The first genuine input hands scroll control back to the user.
  const pinUserIntentBoundRef = useRef(false);
  const cancelPinChain = useCallback(() => {
    for (const frame of pinFramesRef.current) {
      cancelAnimationFrame(frame);
    }
    pinFramesRef.current = [];
    for (const timer of pinEscapeTimersRef.current) {
      clearTimeout(timer);
    }
    pinEscapeTimersRef.current = [];
    if (pinUserIntentBoundRef.current) {
      pinUserIntentBoundRef.current = false;
      const viewport = scrollRef.current;
      if (viewport) {
        viewport.removeEventListener("wheel", cancelPinChain);
        viewport.removeEventListener("touchstart", cancelPinChain);
        viewport.removeEventListener("pointerdown", cancelPinChain);
      }
    }
  }, [scrollRef]);
  const armPinUserIntent = useCallback(() => {
    if (pinUserIntentBoundRef.current) {
      return;
    }
    const viewport = scrollRef.current;
    if (!viewport) {
      return;
    }
    pinUserIntentBoundRef.current = true;
    viewport.addEventListener("wheel", cancelPinChain, { passive: true });
    viewport.addEventListener("touchstart", cancelPinChain, {
      passive: true,
    });
    viewport.addEventListener("pointerdown", cancelPinChain, {
      passive: true,
    });
  }, [cancelPinChain, scrollRef]);
  useLayoutEffect(() => {
    if (pinnedIndex == null) {
      pinChainKeyRef.current = null;
      cancelPinChain();
      if (pinSpacerHeightRef.current !== 0) {
        pinSpacerHeightRef.current = 0;
        setPinSpacerHeight(0);
      }
      return;
    }
    if (pinChainKeyRef.current === pinGroupKey) {
      // The chain already ran (or is running) for this pin; groups churn
      // every stream chunk and must not restart it.
      return;
    }
    pinChainKeyRef.current = pinGroupKey ?? null;
    // A second send within the first chain's 2s window starts a new chain;
    // without this cancel the old chain's pending ticks keep aligning the
    // previous pin (and its timer array is overwritten, orphaning them so
    // they can never be cancelled).
    cancelPinChain();
    armPinUserIntent();
    const trackFrame = (callback: FrameRequestCallback) => {
      const frame = requestAnimationFrame((time) => {
        pinFramesRef.current = pinFramesRef.current.filter(
          (pending) => pending !== frame,
        );
        callback(time);
      });
      pinFramesRef.current.push(frame);
      return frame;
    };
    trackFrame(() => {
      updatePinSpacer();
      trackFrame(() => {
        // Escaping before the alignment is not redundant even though pinning
        // scrolls down: locking back in on a down-scroll is the library's
        // default.
        stopScroll();
        alignGroupToViewport(pinnedIndex, "start", "auto");
        // The alignment scrolls down into the spacer region while a
        // stick-to-bottom resize animation (from the optimistic message
        // growth) is still writing scroll offsets toward the spacer bottom.
        // Every write's scroll event re-locks the follow, and a locked follow
        // later chases the real bottom once the reply grows. The animation
        // converges to the spacer bottom over ~350ms — visually close to the
        // pinned position but not exact. So each escape tick also re-aligns:
        // the chain spans the animation's duration plus its end-of-animation
        // requeue, and the LAST tick runs after the animation has died, so
        // the exact pinned offset wins. The chain spans two seconds: a send
        // that lands while the restored thread's initial virtual positioning
        // and row measurement are still settling interleaves with that churn,
        // which outlasts the resize animation itself. After the chain, the
        // user's own down-scroll re-locks normally.
        pinEscapeTimersRef.current = [
          0, 100, 200, 350, 500, 700, 900, 1100, 1400, 1700, 2000,
        ].map((delay) =>
          window.setTimeout(() => {
            stopScroll();
            alignGroupToViewport(pinnedIndex, "start", "auto");
          }, delay),
        );
        // Settle frames re-align against post-alignment measurement shifts.
        let pending = PIN_SETTLE_FRAMES;
        const scheduleSettle = () => {
          if (pending <= 0) {
            return;
          }
          pending -= 1;
          trackFrame(() => {
            alignGroupToViewport(pinnedIndex, "start", "auto");
            scheduleSettle();
          });
        };
        scheduleSettle();
      });
    });
  }, [
    alignGroupToViewport,
    armPinUserIntent,
    cancelPinChain,
    groups,
    pinGroupKey,
    pinnedIndex,
    stopScroll,
    updatePinSpacer,
  ]);
  useEffect(() => cancelPinChain, [cancelPinChain]);

  useImperativeHandle(
    ref,
    () => ({
      scrollToGroup(groupIndex, options) {
        if (groupIndex < 0 || groupIndex >= groups.length) {
          return;
        }
        // Outline chapter navigation is explicit user intent: a running
        // send-pin chain must not revert it on its next tick.
        cancelPinChain();
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
      cancelPinFollow() {
        cancelPinChain();
      },
    }),
    [
      alignGroupToViewport,
      cancelPinChain,
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
            {renderAfterGroup?.(index)}
          </div>
        ))}
        {pinSpacerHeight > 0 && (
          <div aria-hidden style={{ height: pinSpacerHeight }} />
        )}
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
            {renderAfterGroup?.(virtualRow.index)}
          </div>
        );
      })}
      {pinSpacerHeight > 0 && (
        <div
          aria-hidden
          className="absolute top-0 left-0 w-full"
          style={{
            height: pinSpacerHeight,
            transform: `translateY(${virtualizer.getTotalSize()}px)`,
          }}
        />
      )}
    </div>
  );
});
