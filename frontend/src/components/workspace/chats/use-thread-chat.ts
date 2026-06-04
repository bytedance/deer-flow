"use client";

import { useParams, usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { uuid } from "@/core/utils/uuid";

export function useThreadChat() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const pathname = usePathname();

  const searchParams = useSearchParams();
  const [threadIdState, setThreadIdState] = useState(() => {
    return threadIdFromPath === "new" ? uuid() : threadIdFromPath;
  });

  const [isNewThreadState, setIsNewThreadState] = useState(
    () => threadIdFromPath === "new",
  );

  const newThreadIdRef = useRef(
    threadIdFromPath === "new" ? threadIdState : "",
  );
  const lastNewPathRef = useRef(
    threadIdFromPath === "new" ? pathname : null,
  );
  const isPathNewThread = pathname.endsWith("/new");

  // Generate the next draft thread id synchronously when the route becomes
  // `/new` so child hooks never see the previous thread for one render.
  if (isPathNewThread) {
    if (
      !newThreadIdRef.current ||
      lastNewPathRef.current !== pathname
    ) {
      newThreadIdRef.current = uuid();
      lastNewPathRef.current = pathname;
    }
  } else if (lastNewPathRef.current !== null) {
    lastNewPathRef.current = null;
  }

  const setThreadId = useCallback((value: string) => {
    newThreadIdRef.current = value;
    setThreadIdState(value);
  }, []);

  const setIsNewThread = useCallback((value: boolean) => {
    setIsNewThreadState(value);
  }, []);

  useEffect(() => {
    if (isPathNewThread) {
      if (threadIdState !== newThreadIdRef.current) {
        setIsNewThreadState(true);
        setThreadIdState(newThreadIdRef.current);
      }
      return;
    }
    // Guard: after history.replaceState updates the URL from /chats/new to
    // /chats/{UUID}, Next.js useParams may still return the stale "new" value
    // because replaceState does not trigger router updates. Avoid propagating
    // this invalid thread ID to downstream hooks (e.g. useStream), which would
    // cause a 422 from LangGraph Server.
    if (threadIdFromPath === "new") {
      return;
    }
    setIsNewThreadState(false);
    if (threadIdState !== threadIdFromPath) {
      setThreadIdState(threadIdFromPath);
    }
  }, [isPathNewThread, threadIdFromPath, threadIdState]);

  const threadId = isPathNewThread
    ? newThreadIdRef.current || threadIdState
    : threadIdFromPath === "new"
      ? threadIdState
      : threadIdFromPath;

  const isNewThread = isPathNewThread
    ? threadIdState !== threadId
      ? true
      : isNewThreadState
    : threadIdFromPath === "new"
      ? isNewThreadState
      : false;

  const isMock = searchParams.get("mock") === "true";
  return { threadId, setThreadId, isNewThread, setIsNewThread, isMock };
}
