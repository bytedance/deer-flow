"use client";

import { useParams, usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { uuid } from "@/core/utils/uuid";

export function useThreadChat() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const pathname = usePathname();
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

  useEffect(() => {
    if (isNewPath) {
      const nextThreadId = newThreadIdRef.current ?? uuid();
      newThreadIdRef.current = nextThreadId;
      setIsNewThreadState(true);
      setThreadIdState(nextThreadId);
      return;
    }
    newThreadIdRef.current = null;
    // Guard: after history.replaceState updates the URL from /chats/new to
    // /chats/{UUID}, Next.js useParams may still return the stale "new" value
    // because replaceState does not trigger router updates.  Avoid propagating
    // this invalid thread ID to downstream hooks (e.g. useStream), which would
    // cause a 422 from LangGraph Server.
    if (threadIdFromPath === "new") {
      return;
    }
    setIsNewThreadState(false);
    setThreadIdState(threadIdFromPath);
  }, [isNewPath, threadIdFromPath]);

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
