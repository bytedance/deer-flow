"use client";

import {
  BotIcon,
  FilesIcon,
  PlusIcon,
  SquarePenIcon,
  XIcon,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
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
import { useThreadStream } from "@/core/threads/hooks";
import { textOfMessage } from "@/core/threads/utils";
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

  const { agent } = useAgent(agent_name);

  const threadId = useMemo(
    () => (threadIdFromPath === "new" ? uuid() : threadIdFromPath),
    [threadIdFromPath],
  );

  const [isNewThread, setIsNewThread] = useState(
    () => threadIdFromPath === "new",
  );

  const { showNotification } = useNotification();
  const [thread, sendMessage] = useThreadStream({
    threadId: threadIdFromPath !== "new" ? threadIdFromPath : undefined,
    context: { ...settings.context, agent_name: agent_name },
    onStart: () => {
      setIsNewThread(false);
      history.replaceState(
        null,
        "",
        `/workspace/agents/${agent_name}/chats/${threadId}`,
      );
    },
    onFinish: (state) => {
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
  });

  const title = useMemo(() => {
    let result = isNewThread ? "" : (thread.values?.title ?? "");
    if (result === "Untitled") result = "";
    return result;
  }, [thread.values?.title, isNewThread]);

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

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      void sendMessage(threadId, message, { agent_name });
    },
    [sendMessage, threadId, agent_name],
  );

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ResizablePanelGroup
        orientation="horizontal"
        defaultLayout={{ chat: 100, artifacts: 0 }}
      >
        <ResizablePanel
          className="relative"
          defaultSize={artifactPanelOpen ? 46 : 100}
          minSize={artifactPanelOpen ? 30 : 100}
          id="chat"
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

              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  onClick={() =>
                    router.push(`/workspace/agents/${agent_name}/chats/new`)
                  }
                >
                  <PlusIcon /> {t.agents.newChat}
                </Button>
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
          id="artifacts"
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
