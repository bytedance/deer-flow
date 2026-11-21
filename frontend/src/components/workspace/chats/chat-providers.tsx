"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { BrowserViewProvider } from "@/components/workspace/browser-view";
import { SubtasksProvider } from "@/core/tasks/context";
import { ToolStreamingProvider } from "@/core/tasks/tool-streaming";

export function ChatProviders({ children }: { children: React.ReactNode }) {
  return (
    <SubtasksProvider>
      <ToolStreamingProvider>
        <ArtifactsProvider>
          <BrowserViewProvider>
            <PromptInputProvider>{children}</PromptInputProvider>
          </BrowserViewProvider>
        </ArtifactsProvider>
      </ToolStreamingProvider>
    </SubtasksProvider>
  );
}
