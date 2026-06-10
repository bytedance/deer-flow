"use client";

import { ChevronDownIcon, Loader2Icon } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const LOAD_MORE_THROTTLE_MS = 600;

/**
 * Bottom-of-list "load more" trigger for paginated lists.
 *
 * Mirrors the message-history loader in {@link MessageList}: an
 * ``IntersectionObserver`` sentinel auto-loads the next page as it scrolls
 * into view, with a throttle to avoid firing several pages at once, plus a
 * clickable button fallback for keyboard / no-IO environments. Unlike the
 * message loader this one loads *downward* (older threads appended below), so
 * the observer margin and chevron point down.
 */
export function LoadMoreTrigger({
  hasMore,
  isLoading,
  loadMore,
  className,
}: {
  hasMore?: boolean;
  isLoading?: boolean;
  loadMore?: () => void;
  className?: string;
}) {
  const { t } = useI18n();
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastLoadRef = useRef(0);

  // The throttle can fire a *trailing* call after a delay, so it must read the
  // current props rather than the ones captured when it was scheduled —
  // otherwise it could call `loadMore` after the list already ended.
  const latestRef = useRef({ hasMore, isLoading, loadMore });
  useEffect(() => {
    latestRef.current = { hasMore, isLoading, loadMore };
  });

  const throttledLoadMore = useCallback(() => {
    if (!latestRef.current.hasMore || latestRef.current.isLoading) {
      return;
    }

    const now = Date.now();
    const remaining = LOAD_MORE_THROTTLE_MS - (now - lastLoadRef.current);

    if (remaining <= 0) {
      lastLoadRef.current = now;
      latestRef.current.loadMore?.();
      return;
    }

    if (timeoutRef.current) {
      return;
    }

    timeoutRef.current = setTimeout(() => {
      timeoutRef.current = null;
      const { hasMore: stillHasMore, isLoading: nowLoading, loadMore: load } =
        latestRef.current;
      if (!stillHasMore || nowLoading) {
        return;
      }
      lastLoadRef.current = Date.now();
      load?.();
    }, remaining);
  }, []);

  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasMore) {
      return;
    }

    // No IntersectionObserver (SSR / older test envs): fall back to the button.
    if (typeof IntersectionObserver === "undefined") {
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          throttledLoadMore();
        }
      },
      {
        rootMargin: "0px 0px 120px 0px",
      },
    );

    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, [hasMore, throttledLoadMore]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  if (!hasMore && !isLoading) {
    return null;
  }

  return (
    <div
      ref={sentinelRef}
      className={cn("flex w-full justify-center", className)}
    >
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-muted-foreground hover:text-foreground rounded-full px-3"
        disabled={(isLoading ?? false) || !hasMore}
        onClick={throttledLoadMore}
      >
        {isLoading ? (
          <>
            <Loader2Icon className="mr-2 size-4 animate-spin" />
            {t.common.loading}
          </>
        ) : (
          <>
            <ChevronDownIcon className="mr-2 size-4" />
            {t.common.loadMore}
          </>
        )}
      </Button>
    </div>
  );
}
