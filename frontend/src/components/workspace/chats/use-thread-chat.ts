"use client";

import { useParams, usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { uuid } from "@/core/utils/uuid";

import { reduceThreadChatState } from "./thread-chat-state";

export function useThreadChat() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const pathname = usePathname();

  const searchParams = useSearchParams();
  const [threadId, setThreadId] = useState(() => {
    return threadIdFromPath === "new" ? uuid() : threadIdFromPath;
  });
  const [persistedThreadId, setPersistedThreadId] = useState<string | null>(
    () => (threadIdFromPath === "new" ? null : threadIdFromPath),
  );

  useEffect(() => {
    const nextState = reduceThreadChatState(
      { threadId, persistedThreadId },
      {
        pathname,
        threadIdFromPath,
        nextDraftThreadId: uuid(),
      },
    );

    if (nextState.threadId !== threadId) {
      setThreadId(nextState.threadId);
    }

    if (nextState.persistedThreadId !== persistedThreadId) {
      setPersistedThreadId(nextState.persistedThreadId);
    }
  }, [pathname, persistedThreadId, threadId, threadIdFromPath]);

  const isMock = searchParams.get("mock") === "true";
  const isNewThread = persistedThreadId == null;

  return {
    threadId,
    setThreadId,
    isNewThread,
    setIsNewThread: (value: boolean) => {
      setPersistedThreadId(value ? null : threadId);
    },
    isMock,
    setPersistedThreadId,
  };
}
