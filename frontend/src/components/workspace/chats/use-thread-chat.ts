"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { uuid } from "@/core/utils/uuid";

export function useThreadChat() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const searchParams = useSearchParams();
  const threadId = useMemo(
    () => (threadIdFromPath === "new" ? uuid() : threadIdFromPath),
    [threadIdFromPath],
  );

  const [isNewThread, setIsNewThread] = useState(
    () => threadIdFromPath === "new",
  );
  const isMock = searchParams.get("mock") === "true";
  return { threadId, isNewThread, setIsNewThread, isMock };
}
