"use client";

import { BotIcon, PlusSquare } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import { BrowserTrigger } from "@/components/workspace/browser-view";
import { ChatBox, useThreadChat } from "@/components/workspace/chats";
import { ContextUsageBadge } from "@/components/workspace/context-usage-badge";
import { ExportTrigger } from "@/components/workspace/export-trigger";
import { GoalStatus } from "@/components/workspace/goal-status";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import { KnowledgeScopeSelector } from "@/components/workspace/knowledge-scope-selector";
import {
  MessageList,
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
} from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import {
  SidecarProvider,
  SidecarTrigger,
} from "@/components/workspace/sidecar";
import { ThreadArchiveStatus } from "@/components/workspace/thread-archive-status";
import { ThreadBackgroundTasks } from "@/components/workspace/thread-background-tasks";
import { ThreadSubagentBatches } from "@/components/workspace/thread-subagent-batches";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { TokenUsageIndicator } from "@/components/workspace/token-usage-indicator";
import { Tooltip } from "@/components/workspace/tooltip";
import { useActiveGoal } from "@/components/workspace/use-active-goal";
import { useAgent } from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { useBrowserControlEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import {
  ALL_KNOWLEDGE_SCOPE,
  buildKnowledgeScopeSnapshot,
  KNOWLEDGE_SCOPE_KEY,
  useKnowledgeBaseEnabled,
  type KnowledgeScopeSelection,
} from "@/core/knowledge";
import {
  buildHumanInputResponseText,
  hasOpenHumanInputRequest,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { isHiddenFromUIMessage } from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings, useThreadSettings } from "@/core/settings";
import {
  useThreadMetadata,
  useThreadStream,
  useThreadTokenUsage,
} from "@/core/threads/hooks";
import {
  selectContextUsage,
  threadTokenUsageToTokenUsage,
} from "@/core/threads/token-usage";
import { textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export default function AgentChatPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const canStopStreaming = hasPermission(user, PERMISSIONS.RUNS_CANCEL);
  const router = useRouter();

  const { agent_name } = useParams<{
    agent_name: string;
  }>();

  const { agent } = useAgent(agent_name);

  const { threadId, setThreadId, isNewThread, setIsNewThread, isMock } =
    useThreadChat();
  // `isNewThread` gates history/token-usage fetches until the backend creates
  // the thread. `isWelcomeMode` controls only the centered welcome layout, so
  // it can flip immediately on submit without triggering eager history loads.
  const [isWelcomeMode, setIsWelcomeMode] = useState(isNewThread);
  const [settings, setSettings] = useThreadSettings(threadId);
  const [localSettings, setLocalSettings] = useLocalSettings();
  const { enabled: browserControlEnabled } = useBrowserControlEnabled();
  const { scopeSelectionEnabled } = useKnowledgeBaseEnabled();
  const { tokenUsageEnabled } = useModels();
  const threadTokenUsage = useThreadTokenUsage(
    isNewThread || isMock ? undefined : threadId,
    { enabled: !isMock },
  );
  const threadMetadata = useThreadMetadata(threadId, {
    enabled: !isNewThread && !isMock,
    isMock,
  });
  const backendTokenUsage = threadTokenUsageToTokenUsage(threadTokenUsage.data);
  const contextUsage = selectContextUsage(threadTokenUsage.data);

  const { showNotification } = useNotification();
  const selectorVisible =
    scopeSelectionEnabled && env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";
  const agentKnowledgeEnabled =
    agent !== null &&
    (agent.tool_groups == null || agent.tool_groups.includes("knowledge"));
  const [knowledgeScope, setKnowledgeScope] =
    useState<KnowledgeScopeSelection | null>(null);
  const previousConversationRef = useRef({
    agentName: agent_name,
    threadId,
    isNewThread,
  });

  useEffect(() => {
    setKnowledgeScope((current) => {
      if (!selectorVisible) return null;
      return current ?? ALL_KNOWLEDGE_SCOPE;
    });
  }, [selectorVisible]);

  useEffect(() => {
    const previous = previousConversationRef.current;
    if (previous.agentName !== agent_name || previous.threadId !== threadId) {
      const isNewThreadRouteReplacement =
        previous.agentName === agent_name &&
        previous.isNewThread &&
        !isNewThread;
      if (!isNewThreadRouteReplacement) {
        setKnowledgeScope(selectorVisible ? ALL_KNOWLEDGE_SCOPE : null);
      }
    }
    previousConversationRef.current = {
      agentName: agent_name,
      threadId,
      isNewThread,
    };
  }, [agent_name, isNewThread, selectorVisible, threadId]);

  const currentKnowledgeScopeSnapshot = useMemo(
    () =>
      selectorVisible && agentKnowledgeEnabled && knowledgeScope
        ? buildKnowledgeScopeSnapshot(knowledgeScope)
        : null,
    [agentKnowledgeEnabled, knowledgeScope, selectorVisible],
  );

  useEffect(() => {
    setIsWelcomeMode(isNewThread);
  }, [isNewThread]);

  const {
    thread,
    pendingUsageMessages,
    sendMessage,
    regenerateMessage,
    editAndRegenerateMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    displayThreadId: threadId,
    assistantId: agent_name,
    context: { ...settings.context, agent_name: agent_name },
    isMock,
    onSend: () => {
      setIsWelcomeMode(false);
    },
    onStart: (createdThreadId) => {
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(
        null,
        "",
        `/workspace/agents/${agent_name}/chats/${createdThreadId}`,
      );
      setThreadId(createdThreadId);
      setIsNewThread(false);
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

  const hasThreadMessages = thread.messages.length > 0;

  useEffect(() => {
    if (
      !isNewThread &&
      !isMock &&
      threadMetadata.data === null &&
      !threadMetadata.isLoading &&
      !threadMetadata.isFetching &&
      !isHistoryLoading &&
      !hasMoreHistory &&
      !hasThreadMessages
    ) {
      router.replace(`/workspace/agents/${agent_name}/chats/new`);
    }
  }, [
    agent_name,
    hasMoreHistory,
    hasThreadMessages,
    isHistoryLoading,
    isMock,
    isNewThread,
    router,
    threadMetadata.data,
    threadMetadata.isFetching,
    threadMetadata.isLoading,
  ]);

  const handleSubmit = useCallback(
    (message: PromptInputMessage, options?: InputBoxSubmitOptions) => {
      const scopedOptions = currentKnowledgeScopeSnapshot
        ? {
            ...options,
            additionalKwargs: {
              ...options?.additionalKwargs,
              [KNOWLEDGE_SCOPE_KEY]: currentKnowledgeScopeSnapshot,
            },
          }
        : options;
      const sendPromise = sendMessage(
        threadId,
        message,
        { agent_name },
        scopedOptions,
      );
      if (message.files.length > 0) {
        return sendPromise;
      }
      void sendPromise;
    },
    [currentKnowledgeScopeSnapshot, sendMessage, threadId, agent_name],
  );

  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      let sent = false;
      await sendMessage(
        threadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        { agent_name },
        {
          additionalKwargs: {
            hide_from_ui: true,
            human_input_response: response,
            ...(currentKnowledgeScopeSnapshot
              ? { [KNOWLEDGE_SCOPE_KEY]: currentKnowledgeScopeSnapshot }
              : {}),
          },
          onSent: () => {
            sent = true;
          },
        },
      );
      return sent;
    },
    [agent_name, currentKnowledgeScopeSnapshot, sendMessage, threadId],
  );

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);
  const handleRegenerate = useCallback(
    (messageId: string, supersededMessageIds: string[]) =>
      regenerateMessage(threadId, messageId, supersededMessageIds),
    [regenerateMessage, threadId],
  );
  const handleEditAndRegenerate = useCallback(
    (messageId: string, replacementText: string) =>
      editAndRegenerateMessage(
        threadId,
        messageId,
        replacementText,
        currentKnowledgeScopeSnapshot
          ? { [KNOWLEDGE_SCOPE_KEY]: currentKnowledgeScopeSnapshot }
          : undefined,
      ),
    [currentKnowledgeScopeSnapshot, editAndRegenerateMessage, threadId],
  );

  const tokenUsageInlineMode = tokenUsageEnabled
    ? localSettings.tokenUsage.inlineMode
    : "off";
  const hasTodos = (thread.values.todos?.length ?? 0) > 0;
  const agentBrowserEnabled =
    agent !== null &&
    (agent.tool_groups == null || agent.tool_groups.includes("browser"));
  const browserEnabled =
    !isNewThread && !isMock && browserControlEnabled && agentBrowserEnabled;
  const { activeGoal, hasGoal, setLocalGoal } = useActiveGoal(
    threadId,
    thread.values.goal,
  );
  const hasOpenHumanInputCard = useMemo(
    () =>
      hasOpenHumanInputRequest(
        thread.messages,
        (message) => !isHiddenFromUIMessage(message),
      ),
    [thread.messages],
  );

  return (
    <ThreadContext.Provider value={{ thread, isMock }}>
      <SidecarProvider
        parentThreadId={threadId}
        context={{ ...settings.context, agent_name }}
        isMock={isMock}
      >
        <ChatBox threadId={threadId} browserEnabled={browserEnabled}>
          <div className="relative flex size-full min-h-0 justify-between">
            <header
              className={cn(
                "absolute top-0 right-0 left-0 flex h-12 shrink-0 items-center gap-2 px-2 sm:px-4",
                isWelcomeMode
                  ? "bg-background/0 z-40 backdrop-blur-none"
                  : "bg-background/80 z-30 shadow-xs backdrop-blur",
              )}
            >
              <SidebarTrigger className="md:hidden" />
              {/* Agent badge */}
              <div className="flex min-w-0 shrink-0 items-center gap-1.5 rounded-md border px-2 py-1">
                <BotIcon className="text-primary h-3.5 w-3.5" />
                <span className="hidden max-w-24 truncate text-xs font-medium sm:inline sm:max-w-none">
                  {agent?.display_name?.length
                    ? agent.display_name
                    : (agent?.name ?? agent_name)}
                </span>
              </div>

              <div className="flex min-w-0 flex-1 items-center text-sm font-medium">
                <ThreadTitle
                  threadId={threadId}
                  thread={thread}
                  canonicalTitle={threadMetadata.data?.values?.title}
                />
                {!isNewThread &&
                  !isMock &&
                  env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
                    <ThreadArchiveStatus
                      threadId={threadId}
                      metadata={threadMetadata.data?.metadata}
                    />
                  )}
              </div>
              <div className="flex shrink-0 items-center sm:mr-4">
                {!isNewThread &&
                  !isMock &&
                  env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
                    <ThreadBackgroundTasks threadId={threadId} />
                  )}
                {!isNewThread &&
                  !isMock &&
                  env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
                    <ThreadSubagentBatches threadId={threadId} />
                  )}
                <Tooltip content={t.agents.newChat}>
                  <Button
                    className="px-2 sm:px-3"
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      router.push(`/workspace/agents/${agent_name}/chats/new`);
                    }}
                  >
                    <PlusSquare />
                    <span className="hidden sm:inline">{t.agents.newChat}</span>
                  </Button>
                </Tooltip>
                {tokenUsageEnabled ? (
                  <TokenUsageIndicator
                    threadId={isNewThread ? undefined : threadId}
                    backendUsage={backendTokenUsage}
                    contextUsage={contextUsage}
                    enabled={tokenUsageEnabled}
                    messages={thread.messages}
                    pendingMessages={pendingUsageMessages}
                    preferences={localSettings.tokenUsage}
                    onPreferencesChange={(preferences) =>
                      setLocalSettings("tokenUsage", preferences)
                    }
                  />
                ) : (
                  <ContextUsageBadge contextUsage={contextUsage} />
                )}
                <SidecarTrigger />
                {browserEnabled && <BrowserTrigger />}
                <ExportTrigger threadId={threadId} />
                <ArtifactTrigger />
              </div>
            </header>

            <main className="flex min-h-0 max-w-full grow flex-col">
              <div className="flex min-h-0 flex-1 justify-center">
                <MessageList
                  archiveDownloadsEnabled={
                    isNewThread || isMock || threadMetadata.data != null
                  }
                  className={cn("size-full", !isWelcomeMode && "pt-10")}
                  testId="main-message-list"
                  threadId={threadId}
                  thread={thread}
                  enableConversationOutline
                  paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM}
                  hasMoreHistory={hasMoreHistory}
                  loadMoreHistory={loadMoreHistory}
                  isHistoryLoading={isHistoryLoading}
                  tokenUsageInlineMode={tokenUsageInlineMode}
                  canRegenerate={
                    !isNewThread &&
                    !isMock &&
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                    !isUploading &&
                    !thread.isLoading
                  }
                  onRegenerateMessage={handleRegenerate}
                  canEdit={
                    !isNewThread &&
                    !isMock &&
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                    !isUploading &&
                    !thread.isLoading &&
                    !hasGoal &&
                    !hasOpenHumanInputCard
                  }
                  onEditAndRegenerateMessage={handleEditAndRegenerate}
                  onSubmitHumanInput={
                    isMock || env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                      ? undefined
                      : handleSubmitHumanInput
                  }
                />
              </div>

              <div
                className={cn(
                  "right-0 bottom-0 left-0 z-30 flex justify-center px-3 sm:px-4",
                  isWelcomeMode ? "absolute" : "relative shrink-0 pb-4",
                )}
              >
                <div
                  className={cn(
                    "relative w-full",
                    isWelcomeMode &&
                      "-translate-y-[calc(50vh-48px)] sm:-translate-y-[calc(50vh-96px)]",
                    isWelcomeMode
                      ? "max-w-(--container-width-sm)"
                      : "max-w-(--container-width-md)",
                  )}
                >
                  {(hasGoal || hasTodos) && (
                    <div
                      className={cn(
                        "right-0 left-0 z-0",
                        isWelcomeMode ? "absolute -top-4" : "relative",
                      )}
                    >
                      <div
                        className={cn(
                          "right-0 bottom-0 left-0 flex flex-col",
                          isWelcomeMode ? "absolute" : "relative",
                        )}
                      >
                        {activeGoal && <GoalStatus goal={activeGoal} />}
                        {hasTodos && (
                          <TodoList
                            className="bg-background/5"
                            todos={thread.values.todos ?? []}
                            hidden={false}
                          />
                        )}
                      </div>
                    </div>
                  )}

                  <InputBox
                    className={cn(
                      "bg-background/5 w-full",
                      isWelcomeMode && "-translate-y-2 sm:-translate-y-4",
                    )}
                    isWelcomeMode={isWelcomeMode}
                    threadId={threadId}
                    draftThreadId={isNewThread ? "new" : threadId}
                    draftAgentName={agent_name}
                    defaultModelName={agent?.model}
                    knowledgeScopeControl={
                      selectorVisible && knowledgeScope ? (
                        <KnowledgeScopeSelector
                          agentName={agent_name}
                          disabled={thread.isLoading || isUploading}
                          selection={knowledgeScope}
                          unavailableReason={
                            agentKnowledgeEnabled
                              ? undefined
                              : t.knowledge.scope.agentUnavailable
                          }
                          onChange={setKnowledgeScope}
                        />
                      ) : undefined
                    }
                    autoFocus={isWelcomeMode}
                    status={
                      thread.error
                        ? "error"
                        : thread.isLoading
                          ? "streaming"
                          : "ready"
                    }
                    context={settings.context}
                    extraHeader={
                      isWelcomeMode &&
                      !hasGoal &&
                      !hasTodos && (
                        <AgentWelcome agent={agent} agentName={agent_name} />
                      )
                    }
                    disabled={
                      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                      isUploading ||
                      (selectorVisible && agent === null) ||
                      (!isNewThread && isHistoryLoading)
                    }
                    onContextChange={(context) =>
                      setSettings("context", context)
                    }
                    onGoalChange={setLocalGoal}
                    onSubmit={handleSubmit}
                    onStop={handleStop}
                    canStopStreaming={canStopStreaming}
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
        </ChatBox>
      </SidecarProvider>
    </ThreadContext.Provider>
  );
}
