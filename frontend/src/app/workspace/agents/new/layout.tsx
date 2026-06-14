"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { SubtasksProvider } from "@/core/tasks/context";

// `page.tsx` calls `useThreadStream`, which reaches into the SubtasksProvider
// via `useUpdateLatestMessage`. Without this layout the context throws and the
// new-agent wizard renders the Next.js error boundary (`This page couldn't
// load`). Same Provider stack as the sibling chat layouts so the agent setup
// flow can transition into a live thread without an unmount/remount.
export default function NewAgentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SubtasksProvider>
      <ArtifactsProvider>
        <PromptInputProvider>{children}</PromptInputProvider>
      </ArtifactsProvider>
    </SubtasksProvider>
  );
}
