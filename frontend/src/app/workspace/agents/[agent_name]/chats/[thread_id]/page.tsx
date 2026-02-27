"use client";

import type { Message } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { BotIcon, FilesIcon, XIcon } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { useSidebar } from "@/components/ui/sidebar";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "@/components/workspace/artifacts";
import { InputBox } from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { Tooltip } from "@/components/workspace/tooltip";
import { useAgent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";
import { type AgentThread, type AgentThreadState } from "@/core/threads";
import { useSubmitThread, useThreadStream } from "@/core/threads/hooks";
import { textOfMessage, titleOfThread } from "@/core/threads/utils";
import { uuid } from "@/core/utils/uuid";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export default function AgentChatPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [settings, setSettings] = useLocalSettings();
  const { setOpen: setSidebarOpen } = useSidebar();

  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    selectedArtifact,
  } = useArtifacts();

  const { agent_name, thread_id: threadIdFromPath } = useParams<{
    agent_name: string;
    thread_id: string;
  }>();

  // Agent info
  const { agent } = useAgent(agent_name);

  const isNewThread = useMemo(
    () => threadIdFromPath === "new",
    [threadIdFromPath],
  );

  const [threadId, setThreadId] = useState<string | null>(null);
  useEffect(() => {
    if (threadIdFromPath !== "new") {
      setThreadId(threadIdFromPath);
    } else {
      setThreadId(uuid());
    }
  }, [threadIdFromPath]);

  const { showNotification } = useNotification();
  const [finalState, setFinalState] = useState<AgentThreadState | null>(null);
  const thread = useThreadStream({
    isNewThread,
    threadId,
    onFinish: (state) => {
      setFinalState(state);
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages[state.messages.length - 1];
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            body =
              textContent.length > 200
                ? textContent.substring(0, 200) + "..."
                : textContent;
          }
        }
        showNotification(state.title, { body });
      }
    },
  }) as unknown as UseStream<AgentThreadState>;

  useEffect(() => {
    if (thread.isLoading) setFinalState(null);
  }, [thread.isLoading]);

  const title = useMemo(() => {
    let result = isNewThread
      ? ""
      : titleOfThread(thread as unknown as AgentThread);
    if (result === "Untitled") result = "";
    return result;
  }, [thread, isNewThread]);

  useEffect(() => {
    const agentLabel = agent?.name ? `[${agent.name}] ` : "";
    const pageTitle = isNewThread
      ? t.pages.newChat
      : thread.values?.title && thread.values.title !== "Untitled"
        ? thread.values.title
        : t.pages.untitled;
    if (thread.isThreadLoading) {
      document.title = `Loading... - ${t.pages.appName}`;
    } else {
      document.title = `${agentLabel}${pageTitle} - ${t.pages.appName}`;
    }
  }, [
    isNewThread,
    t.pages.newChat,
    t.pages.untitled,
    t.pages.appName,
    thread.values?.title,
    thread.isThreadLoading,
    agent?.name,
  ]);

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  useEffect(() => {
    setArtifacts(thread.values.artifacts);
    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (thread?.values?.artifacts?.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(thread.values.artifacts[0]!);
      }
    }
  }, [
    autoSelectFirstArtifact,
    selectArtifact,
    setArtifacts,
    thread.values.artifacts,
  ]);

  const artifactPanelOpen = useMemo(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts]);

  const [todoListCollapsed, setTodoListCollapsed] = useState(true);

  const handleSubmit = useSubmitThread({
    isNewThread,
    threadId,
    thread,
    threadContext: {
      ...settings.context,
      thinking_enabled: settings.context.mode !== "flash",
      is_plan_mode:
        settings.context.mode === "pro" || settings.context.mode === "ultra",
      subagent_enabled: settings.context.mode === "ultra",
      agent_name,
    },
    afterSubmit() {
      // Navigate to the permanent thread URL under the agent route
      router.push(`/workspace/agents/${agent_name}/chats/${threadId!}`);
    },
  });

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  if (!threadId) return null;

  return (
    <ThreadContext.Provider value={{ threadId, thread }}>
      <ResizablePanelGroup orientation="horizontal">
        <ResizablePanel
          className="relative"
          defaultSize={artifactPanelOpen ? 46 : 100}
          minSize={artifactPanelOpen ? 30 : 100}
        >
          <div className="relative flex size-full min-h-0 justify-between">
            <header
              className={cn(
                "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center gap-2 px-4",
                isNewThread
                  ? "bg-background/0 backdrop-blur-none"
                  : "bg-background/80 shadow-xs backdrop-blur",
              )}
            >
              {/* Agent badge */}
              <div className="flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1">
                <BotIcon className="text-primary h-3.5 w-3.5" />
                <span className="text-xs font-medium">
                  {agent?.name ?? agent_name}
                </span>
              </div>

              <div className="flex min-w-0 flex-1 items-center text-sm font-medium">
                {title && title !== "Untitled" && (
                  <ThreadTitle threadId={threadId} threadTitle={title} />
                )}
              </div>

              <div>
                {artifacts?.length > 0 && !artifactsOpen && (
                  <Tooltip content="Show artifacts of this conversation">
                    <Button
                      className="text-muted-foreground hover:text-foreground"
                      variant="ghost"
                      onClick={() => {
                        setArtifactsOpen(true);
                        setSidebarOpen(false);
                      }}
                    >
                      <FilesIcon />
                      {t.common.artifacts}
                    </Button>
                  </Tooltip>
                )}
              </div>
            </header>

            <main className="flex min-h-0 max-w-full grow flex-col">
              <div className="flex size-full justify-center">
                <MessageList
                  className={cn("size-full", !isNewThread && "pt-10")}
                  threadId={threadId}
                  thread={thread}
                  messagesOverride={
                    !thread.isLoading && finalState?.messages
                      ? (finalState.messages as Message[])
                      : undefined
                  }
                  paddingBottom={todoListCollapsed ? 160 : 280}
                />
              </div>

              <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
                <div
                  className={cn(
                    "relative w-full",
                    isNewThread && "-translate-y-[calc(50vh-96px)]",
                    isNewThread
                      ? "max-w-(--container-width-sm)"
                      : "max-w-(--container-width-md)",
                  )}
                >
                  <div className="absolute -top-4 right-0 left-0 z-0">
                    <div className="absolute right-0 bottom-0 left-0">
                      <TodoList
                        className="bg-background/5"
                        todos={thread.values.todos ?? []}
                        collapsed={todoListCollapsed}
                        hidden={
                          !thread.values.todos ||
                          thread.values.todos.length === 0
                        }
                        onToggle={() =>
                          setTodoListCollapsed(!todoListCollapsed)
                        }
                      />
                    </div>
                  </div>

                  <InputBox
                    className={cn("bg-background/5 w-full -translate-y-4")}
                    isNewThread={isNewThread}
                    autoFocus={isNewThread}
                    status={thread.isLoading ? "streaming" : "ready"}
                    context={settings.context}
                    extraHeader={
                      isNewThread && (
                        <AgentWelcome agent={agent} agentName={agent_name} />
                      )
                    }
                    disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                    onContextChange={(context) =>
                      setSettings("context", context)
                    }
                    onSubmit={handleSubmit}
                    onStop={handleStop}
                  />
                  {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                    <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                      {t.common.notAvailableInDemoMode}
                    </div>
                  )}
                </div>
              </div>
            </main>
          </div>
        </ResizablePanel>

        <ResizableHandle
          className={cn(
            "opacity-33 hover:opacity-100",
            !artifactPanelOpen && "pointer-events-none opacity-0",
          )}
        />

        <ResizablePanel
          className={cn(
            "transition-all duration-300 ease-in-out",
            !artifactsOpen && "opacity-0",
          )}
          defaultSize={artifactPanelOpen ? 64 : 0}
          minSize={0}
          maxSize={artifactPanelOpen ? undefined : 0}
        >
          <div
            className={cn(
              "h-full p-4 transition-transform duration-300 ease-in-out",
              artifactPanelOpen ? "translate-x-0" : "translate-x-full",
            )}
          >
            {selectedArtifact ? (
              <ArtifactFileDetail
                className="size-full"
                filepath={selectedArtifact}
                threadId={threadId}
              />
            ) : (
              <div className="relative flex size-full justify-center">
                <div className="absolute top-1 right-1 z-30">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => setArtifactsOpen(false)}
                  >
                    <XIcon />
                  </Button>
                </div>
                {thread.values.artifacts?.length === 0 ? (
                  <div className="text-muted-foreground flex h-40 flex-col items-center justify-center gap-2 text-sm">
                    <FilesIcon className="h-6 w-6" />
                    <span>No artifact selected</span>
                  </div>
                ) : (
                  <div className="flex size-full max-w-(--container-width-sm) flex-col justify-center p-4 pt-8">
                    <header className="shrink-0">
                      <h2 className="text-lg font-medium">Artifacts</h2>
                    </header>
                    <main className="min-h-0 grow">
                      <ArtifactFileList
                        className="max-w-(--container-width-sm) p-4 pt-12"
                        files={thread.values.artifacts ?? []}
                        threadId={threadId}
                      />
                    </main>
                  </div>
                )}
              </div>
            )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </ThreadContext.Provider>
  );
}
