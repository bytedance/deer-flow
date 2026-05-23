"use client";

import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { useEffect, useMemo, useState } from "react";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { useThreadSettings } from "@/core/settings";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { InputBox } from "../input-box";
import { MessageList, MESSAGE_LIST_DEFAULT_PADDING_BOTTOM } from "../messages";

import { TableCanvas } from "./table-canvas";
import { TableResourceList } from "./table-resource-list";

const EMBED_PREFIX = "embed:";

export function TableWorkspace({
  threadId,
  thread,
  isNewThread,
  onSubmit,
  onStop,
}: {
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  isNewThread: boolean;
  onSubmit: (message: PromptInputMessage) => void;
  onStop: () => void;
}) {
  const [selectedTableId, setSelectedTableId] = useState<string | null>(null);
  const [selectedTableName, setSelectedTableName] = useState<string | null>(
    null,
  );
  const [settings, setSettings] = useThreadSettings(threadId);

  // Extract the latest embed URL from agent artifacts
  const agentEmbedUrl = useMemo(() => {
    const artifacts = thread.values?.artifacts;
    if (!artifacts?.length) return null;
    // Find the last embed artifact
    for (let i = artifacts.length - 1; i >= 0; i--) {
      const a = artifacts[i];
      if (a?.startsWith(EMBED_PREFIX)) {
        return a.slice(EMBED_PREFIX.length);
      }
    }
    return null;
  }, [thread.values?.artifacts]);

  // When agent produces an embed URL, clear manual table selection
  // so the canvas shows the agent's view
  const [lastAgentUrl, setLastAgentUrl] = useState<string | null>(null);
  useEffect(() => {
    if (agentEmbedUrl && agentEmbedUrl !== lastAgentUrl) {
      setLastAgentUrl(agentEmbedUrl);
      setSelectedTableId(null);
      setSelectedTableName(null);
    }
  }, [agentEmbedUrl, lastAgentUrl]);

  // Active embed: agent URL unless user manually selected a table after
  const activeEmbedUrl = selectedTableId ? null : agentEmbedUrl;

  return (
    <ResizablePanelGroup
      id="table-workspace-panels"
      orientation="horizontal"
      defaultLayout={{ chat: 30, resources: 20, canvas: 50 }}
    >
      {/* Left pane: Chat */}
      <ResizablePanel
        className="relative"
        defaultSize={30}
        id="chat"
        minSize={20}
      >
        <div className="relative flex size-full min-h-0 flex-col">
          <header
            className={cn(
              "absolute top-0 right-0 left-0 z-30 flex h-10 shrink-0 items-center px-3",
              "bg-background/80 shadow-xs backdrop-blur",
            )}
          >
            <span className="text-sm font-medium">Chat</span>
          </header>
          <main className="flex min-h-0 max-w-full grow flex-col">
            <div className="flex size-full justify-center">
              <MessageList
                className="size-full pt-10"
                threadId={threadId}
                thread={thread}
                paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM}
              />
            </div>
            <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-2">
              <div className="relative w-full max-w-full">
                <InputBox
                  className="bg-background/5 w-full -translate-y-3"
                  isNewThread={isNewThread}
                  threadId={threadId}
                  autoFocus
                  status={
                    thread.error
                      ? "error"
                      : thread.isLoading
                        ? "streaming"
                        : "ready"
                  }
                  context={settings.context}
                  onContextChange={(context) => setSettings("context", context)}
                  onSubmit={onSubmit}
                  onStop={onStop}
                />
              </div>
            </div>
          </main>
        </div>
      </ResizablePanel>

      <ResizableHandle
        id="chat-resources-separator"
        className="opacity-33 hover:opacity-100"
      />

      {/* Center pane: Resource list */}
      <ResizablePanel defaultSize={20} id="resources" minSize={12}>
        <TableResourceList
          selectedTableId={selectedTableId}
          onSelectTable={(id, name) => {
            setSelectedTableId(id);
            setSelectedTableName(name);
          }}
        />
      </ResizablePanel>

      <ResizableHandle
        id="resources-canvas-separator"
        className="opacity-33 hover:opacity-100"
      />

      {/* Right pane: Canvas */}
      <ResizablePanel defaultSize={50} id="canvas" minSize={20}>
        <TableCanvas
          tableId={selectedTableId}
          tableName={selectedTableName}
          embedUrl={activeEmbedUrl}
        />
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}
