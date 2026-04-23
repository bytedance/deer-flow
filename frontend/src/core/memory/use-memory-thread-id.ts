"use client";

import { useParams, usePathname } from "next/navigation";
import { useMemo } from "react";

function threadIdFromChatPath(pathname: string): string | null {
  const m = /\/workspace\/(?:agents\/[^/]+\/)?chats\/([^/]+)/.exec(pathname);
  const id = m?.[1];
  if (!id || id === "new") {
    return null;
  }
  return id;
}

/**
 * LangGraph thread id for memory API (`thread_id` query), from the workspace chat URL.
 * Returns null on chat list, new chat, or outside `/workspace/.../chats/...`.
 */
export function useMemoryThreadId(): string | null {
  const params = useParams<{ thread_id?: string }>();
  const pathname = usePathname();

  return useMemo(() => {
    const fromParams =
      typeof params.thread_id === "string" &&
      params.thread_id.length > 0 &&
      params.thread_id !== "new"
        ? params.thread_id
        : null;
    return fromParams ?? threadIdFromChatPath(pathname);
  }, [params.thread_id, pathname]);
}
