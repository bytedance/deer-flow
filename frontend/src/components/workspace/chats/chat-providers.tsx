"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { SubtasksProvider } from "@/core/tasks/context";

type RouteParams = {
  thread_id?: string | string[];
};

function firstParam(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

export function ChatProviders({ children }: { children: ReactNode }) {
  const params = useParams<RouteParams>();
  const threadId = firstParam(params.thread_id);

  return (
    // Thread navigation must reset the full chat-scoped provider tree so
    // prompt, artifact, and subtask state cannot leak across threads.
    <SubtasksProvider key={threadId}>
      <ArtifactsProvider>
        <PromptInputProvider>{children}</PromptInputProvider>
      </ArtifactsProvider>
    </SubtasksProvider>
  );
}
