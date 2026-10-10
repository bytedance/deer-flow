"use client";

import { notifyManager, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useSyncExternalStore } from "react";

import { cachedThreadUnread, useMarkThreadRead } from "@/core/threads/activity";

/**
 * Keep the open conversation read. Marks `threadId` read (through
 * `useMarkThreadRead`, so every trigger is debounced and is a no-op while the
 * cached `unread` is `false`):
 * - once the thread has loaded (`enabled`);
 * - whenever its cached `unread` flips to `true` while it is open (a poll
 *   saw a scheduled run in it change, or another device's state arrived);
 * - when the tab becomes visible again.
 *
 * Returns `markRead` for the chat's own triggers (a stream in this thread
 * finished, or a joined run ended).
 */
export function useMarkOpenThreadRead(
  threadId: string | null | undefined,
  { enabled }: { enabled: boolean },
): () => void {
  const queryClient = useQueryClient();
  const activeThreadId = enabled && threadId ? threadId : null;
  const markRead = useMarkThreadRead(activeThreadId);

  // Batched like TanStack's own `useIsFetching`: cache events raised while
  // another component renders (an observer building its query) are delivered
  // after that render, once per batch.
  const subscribe = useCallback(
    (onChange: () => void) =>
      queryClient.getQueryCache().subscribe(notifyManager.batchCalls(onChange)),
    [queryClient],
  );
  const cachedUnread = useSyncExternalStore(
    subscribe,
    () =>
      activeThreadId === null
        ? undefined
        : cachedThreadUnread(queryClient, activeThreadId),
    () => undefined,
  );

  useEffect(() => {
    if (activeThreadId === null || cachedUnread === false) {
      return;
    }
    markRead();
  }, [activeThreadId, cachedUnread, markRead]);

  useEffect(() => {
    if (activeThreadId === null) {
      return;
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        markRead();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [activeThreadId, markRead]);

  return markRead;
}
