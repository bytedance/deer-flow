"use client";

import { useParams, usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { uuid } from "@/core/utils/uuid";

export const THREAD_CHAT_RESET_EVENT = "deer-flow:thread-chat-reset";

type ThreadChatResetDetail = {
  deletedThreadId: string;
  nextPath: string;
  force?: boolean;
};

export function resetThreadChatAfterDelete(detail: ThreadChatResetDetail) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(
    new CustomEvent<ThreadChatResetDetail>(THREAD_CHAT_RESET_EVENT, {
      detail,
    }),
  );
}

export function useThreadChat() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const pathname = usePathname();
  // Render-time values use the committed browser URL. The sync effect below
  // intentionally watches the reactive pathname so client navigation still
  // schedules a reset when window.location is stale during render.
  const actualPathname =
    typeof window === "undefined" ? pathname : window.location.pathname;
  const isNewPath = actualPathname.endsWith("/new");
  const newThreadIdRef = useRef<string | null>(
    threadIdFromPath === "new" ? uuid() : null,
  );

  if (isNewPath && !newThreadIdRef.current) {
    newThreadIdRef.current = uuid();
  }

  const searchParams = useSearchParams();
  const [threadId, setThreadIdState] = useState(() => {
    return threadIdFromPath === "new"
      ? (newThreadIdRef.current ?? uuid())
      : threadIdFromPath;
  });

  const [isNewThreadState, setIsNewThreadState] = useState(
    () => threadIdFromPath === "new",
  );

  const resetToNewThread = useCallback(() => {
    const nextThreadId = uuid();
    newThreadIdRef.current = nextThreadId;
    setIsNewThreadState(true);
    setThreadIdState(nextThreadId);
  }, []);

  useEffect(() => {
    if (pathname.endsWith("/new")) {
      const nextThreadId = newThreadIdRef.current ?? uuid();
      newThreadIdRef.current = nextThreadId;
      setIsNewThreadState(true);
      setThreadIdState(nextThreadId);
      return;
    }
    newThreadIdRef.current = null;
    // Native history updates the canonical pathname but preserves the route
    // tree, so useParams may still return the stale "new" value. Avoid passing
    // it to downstream hooks (e.g. useStream), which would cause a 422.
    if (threadIdFromPath === "new") {
      return;
    }
    setIsNewThreadState(false);
    setThreadIdState(threadIdFromPath);
  }, [pathname, threadIdFromPath]);

  useEffect(() => {
    const handleReset = (event: Event) => {
      const detail = (event as CustomEvent<ThreadChatResetDetail>).detail;
      if (!detail?.nextPath) {
        return;
      }

      const currentPathname = window.location.pathname;
      const isDeletingCurrentThread =
        detail.force === true ||
        detail.deletedThreadId === threadId ||
        detail.deletedThreadId === threadIdFromPath ||
        currentPathname.endsWith(`/${detail.deletedThreadId}`);

      if (!isDeletingCurrentThread) {
        return;
      }

      // URL replacement is owned by the caller's Next router action; this hook
      // only resets local chat state so the router state and browser URL stay
      // in sync.
      resetToNewThread();
    };

    window.addEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
    return () =>
      window.removeEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
  }, [resetToNewThread, threadId, threadIdFromPath]);

  const setThreadId = useCallback((nextThreadId: string) => {
    newThreadIdRef.current = null;
    setThreadIdState(nextThreadId);
  }, []);

  const setIsNewThread = useCallback((nextIsNewThread: boolean) => {
    if (!nextIsNewThread) {
      newThreadIdRef.current = null;
    }
    setIsNewThreadState(nextIsNewThread);
  }, []);

  const isMock = searchParams.get("mock") === "true";
  return {
    threadId: isNewPath ? (newThreadIdRef.current ?? threadId) : threadId,
    setThreadId,
    isNewThread: isNewPath ? true : isNewThreadState,
    setIsNewThread,
    isMock,
  };
}
