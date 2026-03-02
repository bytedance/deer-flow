"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { uuid } from "@/core/utils/uuid";

export function useThreadChat() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();

  const threadId = useMemo(
    () => (threadIdFromPath === "new" ? uuid() : threadIdFromPath),
    [threadIdFromPath],
  );

  const [isNewThread, setIsNewThread] = useState(
    () => threadIdFromPath === "new",
  );

  return { threadId, isNewThread, setIsNewThread };
}
