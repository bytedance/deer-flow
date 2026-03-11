"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { SubtasksProvider } from "@/core/tasks/context";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { thread_id } = useParams<{ thread_id: string }>();
  const prevThreadId = useRef(thread_id);

  // Increment only when navigating TO "new" from a non-"new" route.
  // This forces a full remount of the subtree for a fresh new-chat state,
  // without remounting when the URL transitions from "new" → actual-id
  // (which would interrupt streaming).
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (thread_id === "new" && prevThreadId.current !== "new") {
      setGeneration((g) => g + 1);
    }
    prevThreadId.current = thread_id;
  }, [thread_id]);

  return (
    <SubtasksProvider key={generation}>
      <ArtifactsProvider>
        <PromptInputProvider>{children}</PromptInputProvider>
      </ArtifactsProvider>
    </SubtasksProvider>
  );
}
