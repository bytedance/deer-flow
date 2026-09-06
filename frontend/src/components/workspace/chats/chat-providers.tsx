"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { BrowserViewProvider } from "@/components/workspace/browser-view";
import { SubtasksProvider } from "@/core/tasks/context";

export function ChatProviders({ children }: { children: React.ReactNode }) {
  return (
    <SubtasksProvider>
      <ArtifactsProvider>
        <BrowserViewProvider>
          <PromptInputProvider>{children}</PromptInputProvider>
        </BrowserViewProvider>
      </ArtifactsProvider>
    </SubtasksProvider>
  );
}
