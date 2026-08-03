"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { SubtasksProvider } from "@/core/tasks/context";
import { ToolStreamingProvider } from "@/core/tasks/tool-streaming";

export default function AgentChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SubtasksProvider>
      <ToolStreamingProvider>
        <ArtifactsProvider>
          <PromptInputProvider>{children}</PromptInputProvider>
        </ArtifactsProvider>
      </ToolStreamingProvider>
    </SubtasksProvider>
  );
}
