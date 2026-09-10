"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Folder } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import { BrowserTrigger } from "@/components/workspace/browser-view";
import { ContextUsageBadge } from "@/components/workspace/context-usage-badge";
import { ExportTrigger } from "@/components/workspace/export-trigger";
import { GoalStatus } from "@/components/workspace/goal-status";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
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
import { ThreadScheduledTasksLink } from "@/components/workspace/thread-scheduled-tasks-link";
import { ThreadSubagentBatches } from "@/components/workspace/thread-subagent-batches";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { TokenUsageIndicator } from "@/components/workspace/token-usage-indicator";
import { useActiveGoal } from "@/components/workspace/use-active-goal";
import { Welcome } from "@/components/workspace/welcome";
import { useBrowserControlEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildHumanInputResponseText,
  hasOpenHumanInputRequest,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { isHiddenFromUIMessage } from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useProject } from "@/core/projects";
import { useLocalSettings, useThreadSettings } from "@/core/settings";
import { createThread } from "@/core/threads/api";
import {
  useBranchThread,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  useThreadMetadata,
  useThreadStream,
  useThreadTokenUsage,
} from "@/core/threads/hooks";
import {
  selectContextUsage,
  threadTokenUsageToTokenUsage,
} from "@/core/threads/token-usage";
import { projectIdOfThread, textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ChatBox } from "./chat-box";
import { useSpecificChatMode } from "./use-chat-mode";
import { useThreadChat } from "./use-thread-chat";

export default function ChatPage() {
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { threadId, setThreadId, isNewThread, setIsNewThread, isMock } =
    useThreadChat();
  // Project-scoped new chat: `/workspace/chats/new?project={id}` assigns the
  // thread to the project on the FIRST submit — primarily via an explicit
  // `POST /api/threads` pre-create with `project_id`, with the run-request
  // metadata seed as the fallback channel (the SDK's own threads.create
  // strips the reserved key, so the seed alone races the sidebar). Only
  // meaningful while the thread is still lazy (`isNewThread`); once
  // materialized the URL is replaced with the thread route and the param is
  // gone. Invalid ids are dropped by backend admission.
  const projectParam = isNewThread ? searchParams.get("project") : null;
  // `isNewThread` tracks whether the backend has the thread yet — gates the
  // SDK's history fetch (see issue #2746).  `isWelcomeMode` is the visual
  // welcome layout (centered input, hero, quick actions); we flip it to false
  // the moment the user submits so the UI animates immediately, even though
  // `isNewThread` stays true until the backend actually creates the thread.
  const [isWelcomeMode, setIsWelcomeMode] = useState(isNewThread);
  const queryClient = useQueryClient();
  const [settings, setSettings] = useThreadSettings(threadId);
  const [localSettings, setLocalSettings] = useLocalSettings();
  const { enabled: browserControlEnabled } = useBrowserControlEnabled();
  const { tokenUsageEnabled } = useModels();
  const threadTokenUsage = useThreadTokenUsage(
    isNewThread || isMock ? undefined : threadId,
    { enabled: !isMock },
  );
  const threadMetadata = useThreadMetadata(threadId, {
    enabled: !isNewThread && !isMock,
    isMock,
  });
  const branchThread = useBranchThread();
  const backendTokenUsage = threadTokenUsageToTokenUsage(threadTokenUsage.data);
  const contextUsage = selectContextUsage(threadTokenUsage.data);
  const mountedRef = useRef(false);
  useSpecificChatMode();

  useEffect(() => {
    mountedRef.current = true;
  }, []);

  // Keep welcome layout in sync when navigating between threads (sidebar
  // clicks, "new chat" button).  Submitting in /chats/new flips the layout
  // via onSend below — `isNewThread` stays true until onStart, so this effect
  // is harmless during the submit transition.
  useEffect(() => {
    setIsWelcomeMode(isNewThread);
  }, [isNewThread]);

  const { showNotification } = useNotification();

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
    context: settings.context,
    isMock,
    // onSend only animates the UI; do NOT flip `isNewThread` here — the
    // LangGraph SDK eagerly fetches /history the moment it receives a
    // thread id and assumes the thread exists on the backend (issue #2746).
    onSend: () => {
      setIsWelcomeMode(false);
    },
    onStart: (createdThreadId) => {
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(null, "", `/workspace/chats/${createdThreadId}`);
      setThreadId(createdThreadId);
      setIsNewThread(false);
    },
    onFinish: (state) => {
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages.at(-1);
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
      router.replace("/workspace/chats/new");
    }
  }, [
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

  // Born assigned: pre-create the thread row with its project so the sidebar
  // lists it under the project immediately. Idempotent server-side on
  // `thread_id`, so retrying the same first message (same `threadId` while
  // `isNewThread`) reuses the existing row instead of double-creating. This
  // is the sole membership channel — run requests never carry the project
  // key.
  //
  // Also runs before InputBox issues a `/goal <condition>` PUT (via
  // `onPrepareThread`): the goal endpoint materializes a missing thread row
  // itself, and an unassigned row would make this later idempotent create a
  // membership no-op.
  const ensureProjectThread = useCallback(async () => {
    if (!projectParam) {
      return;
    }
    try {
      await createThread(threadId, projectParam);
      void queryClient.invalidateQueries({
        queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      });
    } catch (error) {
      // Any failure (e.g. the project was deleted/archived between page load
      // and submit): do NOT submit unassigned. Reject so PromptInput keeps
      // the composer's text for a retry; the send in-flight guard is never
      // engaged on this path, so retrying works immediately.
      toast.error(t.projects.projectUnavailable);
      throw error;
    }
  }, [threadId, projectParam, queryClient, t]);

  // Submission fence. The cleanup runs when `threadId` changes (conversation
  // switch on a persisted page — sidebar navigation keeps this component
  // mounted), when the new-chat project scope changes (the sidebar "New
  // chat" link can drop `?project=` without a pathname change), or on
  // unmount. handleSubmit awaits the project pre-create before sending, and
  // a navigation during that await must not let the stale continuation
  // start a run for the abandoned conversation: its onStart would rewrite
  // the newly selected conversation's URL and its completion would clear
  // the new composer.
  const submissionEpochRef = useRef(0);
  useEffect(() => {
    return () => {
      submissionEpochRef.current += 1;
    };
  }, [threadId, projectParam]);

  const handleSubmit = useCallback(
    async (message: PromptInputMessage, options?: InputBoxSubmitOptions) => {
      const submissionEpoch = submissionEpochRef.current;
      await ensureProjectThread();
      // Conversation switched (or the page unmounted) while the project
      // pre-create was pending: drop the submission. Reject silently — the
      // user has already moved on, so a toast would land on the new
      // conversation — and PromptInput keeps the current composer text.
      if (submissionEpochRef.current !== submissionEpoch) {
        throw new Error("thread-submission-stale");
      }
      const sendPromise = sendMessage(threadId, message, undefined, options);
      if (message.files.length > 0) {
        return sendPromise;
      }
      void sendPromise;
    },
    [sendMessage, threadId, ensureProjectThread],
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
        undefined,
        {
          additionalKwargs: {
            hide_from_ui: true,
            human_input_response: response,
          },
          onSent: () => {
            sent = true;
          },
        },
      );
      return sent;
    },
    [sendMessage, threadId],
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
      editAndRegenerateMessage(threadId, messageId, replacementText),
    [editAndRegenerateMessage, threadId],
  );
  const handleBranchTurn = useCallback(
    async (messageId: string, messageIds: string[]) => {
      if (
        isNewThread ||
        isMock ||
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
      ) {
        return;
      }

      try {
        const response = await branchThread.mutateAsync({
          threadId,
          messageId,
          messageIds,
        });
        toast.success(t.conversation.branchCreated);
        router.push(`/workspace/chats/${response.thread_id}`);
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t.conversation.branchFailed,
        );
      }
    },
    [branchThread, isMock, isNewThread, router, t, threadId],
  );

  const tokenUsageInlineMode = tokenUsageEnabled
    ? localSettings.tokenUsage.inlineMode
    : "off";
  const hasTodos = (thread.values.todos?.length ?? 0) > 0;
  const browserEnabled = !isNewThread && !isMock && browserControlEnabled;
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

  // Project affiliation chip: shown once the materialized thread's metadata
  // carries `deerflow_project_id` (written by the create/move endpoints and
  // exposed here read-only).
  const affiliatedProjectId =
    !isNewThread && !isMock && threadMetadata.data
      ? projectIdOfThread(threadMetadata.data)
      : null;

  return (
    <ThreadContext.Provider value={{ thread, isMock }}>
      <SidecarProvider
        parentThreadId={threadId}
        context={settings.context}
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
              {!isMock && <SidebarTrigger className="md:hidden" />}
              <div className="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium">
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
                {affiliatedProjectId && (
                  <ProjectAffiliationBadge projectId={affiliatedProjectId} />
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
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
                {!isNewThread && !isMock && (
                  <ThreadScheduledTasksLink threadId={threadId} />
                )}
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
                    !branchThread.isPending &&
                    !hasGoal &&
                    !hasOpenHumanInputCard
                  }
                  onEditAndRegenerateMessage={handleEditAndRegenerate}
                  onSubmitHumanInput={
                    isMock || env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                      ? undefined
                      : handleSubmitHumanInput
                  }
                  canBranch={
                    !isNewThread &&
                    !isMock &&
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                    !isUploading &&
                    !thread.isLoading &&
                    !branchThread.isPending
                  }
                  onBranchTurn={handleBranchTurn}
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
                  {mountedRef.current ? (
                    <InputBox
                      className={cn(
                        "bg-background/5 w-full",
                        isWelcomeMode && "-translate-y-2 sm:-translate-y-4",
                      )}
                      isWelcomeMode={isWelcomeMode}
                      threadId={threadId}
                      draftThreadId={isNewThread ? "new" : threadId}
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
                        !hasTodos && <Welcome mode={settings.context.mode} />
                      }
                      disabled={
                        isMock ||
                        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                        isUploading ||
                        (!isNewThread && isHistoryLoading)
                      }
                      onContextChange={(context) =>
                        setSettings("context", context)
                      }
                      onGoalChange={setLocalGoal}
                      onPrepareThread={ensureProjectThread}
                      onSubmit={handleSubmit}
                      onStop={handleStop}
                    />
                  ) : (
                    <div
                      aria-hidden="true"
                      className={cn(
                        "bg-background/5 h-32 w-full rounded-2xl",
                        isWelcomeMode && "-translate-y-2 sm:-translate-y-4",
                      )}
                    />
                  )}
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

/**
 * Small chip in the chat header linking to the thread's project. Hidden
 * while the project lookup is pending or when it fails (e.g. the project
 * was deleted) — an unresolvable affiliation degrades silently.
 */
function ProjectAffiliationBadge({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId);
  if (!project) {
    return null;
  }
  return (
    <Link
      href={`/workspace/projects/${encodeURIComponent(project.id)}`}
      className="text-muted-foreground hover:text-foreground inline-flex max-w-40 shrink-0 items-center gap-1 truncate rounded-full border px-2 py-0.5 text-xs font-normal transition-colors"
    >
      <Folder className="size-3 shrink-0" />
      <span className="truncate">{project.name}</span>
    </Link>
  );
}
