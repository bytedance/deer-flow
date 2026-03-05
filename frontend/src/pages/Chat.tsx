import type { Message } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useQueryClient } from "@tanstack/react-query";
import {
  FilesIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { useSidebar } from "@/components/ui/sidebar";
import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "@/components/workspace/artifacts";
import { ContextPanel } from "@/components/workspace/context-panel";
import { InputBox } from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { QuickActions } from "@/components/workspace/quick-actions";
import { useRightPanel } from "@/components/workspace/right-panel-context";
import { SessionUsageDisplay } from "@/components/workspace/session-usage-display";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { Tooltip } from "@/components/workspace/tooltip";
import { Welcome } from "@/components/workspace/welcome";
import { useAuth } from "@/core/auth";
import { authFetch } from "@/core/auth/fetch";
import { getBackendBaseURL, useAppConfig } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { getUserModelPreferences, setUserModelPreferences } from "@/core/models/api";
import {
  getRuntimeModelSpec,
  resolveThinkingEffortForModel,
  useModels,
} from "@/core/models/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";
import { getLocalSettings } from "@/core/settings/local";
import { type AgentThread, type AgentThreadState } from "@/core/threads";
import {
  type ThreadResubmitOptions,
  useSubmitThread,
  useThreadStream,
} from "@/core/threads/hooks";
import { resetTurnUsage } from "@/core/threads/usage-context";
import {
  pathOfThread,
  textOfMessage,
  titleOfThread,
} from "@/core/threads/utils";
import { uuid } from "@/core/utils/uuid";
import { env } from "@/env";
import { cn } from "@/lib/utils";

const RESUBMIT_TTL_MS = 60_000;
const RESUBMIT_DELAY_MS = 150;
const RIGHT_PANEL_WIDTH_STORAGE_KEY = "right_panel_width_px";
const RIGHT_PANEL_MIN_WIDTH_PX = 280;
const RIGHT_PANEL_MAX_WIDTH_PX = 520;

interface TruncateMessagesResponse {
  success: boolean;
  messages_kept: number;
  messages_removed: number;
  checkpoint_id?: string | null;
  checkpoint_ns?: string | null;
  checkpoint_map?: Record<string, unknown>;
}

interface PendingResubmitData {
  text: string;
  timestamp: number;
  checkpoint?: ThreadResubmitOptions["checkpoint"];
  attempts?: number;
}

function ChatInner() {
  const { t } = useI18n();
  const { brand } = useAppConfig();
  const navigate = useNavigate();
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
  const { threadId: threadIdFromPath } = useParams<{ threadId: string }>();
  const [searchParams] = useSearchParams();
  const promptInputController = usePromptInputController();

  const inputInitialValue = useMemo(() => {
    if (threadIdFromPath !== "new" || searchParams.get("mode") !== "skill") {
      return undefined;
    }
    return t.inputBox.createSkillPrompt;
  }, [threadIdFromPath, searchParams, t.inputBox.createSkillPrompt]);

  const lastInitialValueRef = useRef<string | undefined>(undefined);
  const setInputRef = useRef(promptInputController.textInput.setInput);
  const resubmitInFlightThreadRef = useRef<string | null>(null);
  const [modelPrefsHydrated, setModelPrefsHydrated] = useState(false);
  const lastPersistedModelPrefsRef = useRef<string>("");
  setInputRef.current = promptInputController.textInput.setInput;

  useEffect(() => {
    if (
      inputInitialValue &&
      inputInitialValue !== lastInitialValueRef.current
    ) {
      lastInitialValueRef.current = inputInitialValue;
      setTimeout(() => {
        setInputRef.current(inputInitialValue);
        const textarea = document.querySelector("textarea");
        if (textarea) {
          textarea.focus();
          textarea.selectionStart = textarea.value.length;
          textarea.selectionEnd = textarea.value.length;
        }
      }, 100);
    }
  }, [inputInitialValue]);

  const isNewThread = useMemo(
    () => threadIdFromPath === "new",
    [threadIdFromPath],
  );

  const generatedThreadIdRef = useRef<string>(uuid());
  const threadId = isNewThread
    ? generatedThreadIdRef.current
    : (threadIdFromPath ?? null);

  const { showNotification } = useNotification();
  const queryClient = useQueryClient();

  const thread = useThreadStream({
    isNewThread,
    threadId,
    onFinish: (state) => {
      if (isNewThread && threadIdFromPath === "new" && threadId) {
        void navigate(pathOfThread(threadId), { replace: true });
      }
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages.at(-1);
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            if (textContent.length > 200) {
              body = textContent.substring(0, 200) + "...";
            } else {
              body = textContent;
            }
          }
        }
        showNotification(state.title, {
          body,
        });
      }
    },
  }) as unknown as UseStream<AgentThreadState>;

  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isTransitioningConversation, setIsTransitioningConversation] =
    useState(false);
  const [hasPendingSubmit, setHasPendingSubmit] = useState(false);
  const hasConversation = useMemo(() => {
    const streamMessages = thread.messages ?? [];
    const valueMessages = Array.isArray(thread.values?.messages)
      ? thread.values.messages
      : [];
    return (
      thread.isLoading || streamMessages.length > 0 || valueMessages.length > 0
    );
  }, [thread.isLoading, thread.messages, thread.values?.messages]);
  const showLanding = isNewThread && !hasConversation && !hasPendingSubmit;

  const title = useMemo(() => {
    let result = isNewThread
      ? ""
      : titleOfThread(thread as unknown as AgentThread);
    if (result === "Untitled") {
      result = "";
    }
    return result;
  }, [thread, isNewThread]);

  useEffect(() => {
    const pageTitle = isNewThread
      ? t.pages.newChat
      : thread.values?.title && thread.values.title !== "Untitled"
        ? thread.values.title
        : t.pages.untitled;
    if (thread.isThreadLoading) {
      document.title = `Loading... - ${brand.name}`;
    } else {
      document.title = `${pageTitle} - ${brand.name}`;
    }
  }, [
    brand.name,
    isNewThread,
    t.pages.newChat,
    t.pages.untitled,
    thread.values.title,
    thread.isThreadLoading,
  ]);

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);

  useEffect(() => {
    setArtifacts(thread.values.artifacts);
    if (env.VITE_STATIC_WEBSITE_ONLY === "true" && autoSelectFirstArtifact) {
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
    if (env.VITE_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts]);

  const [todoListCollapsed, setTodoListCollapsed] = useState(true);
  const { open: todoPanelOpen, setOpen: setTodoPanelOpen } = useRightPanel();
  const showTodoPanel = todoPanelOpen;
  const [rightPanelWidth, setRightPanelWidth] = useState(() => {
    if (typeof window === "undefined") {
      return 320;
    }
    const raw = window.localStorage.getItem(RIGHT_PANEL_WIDTH_STORAGE_KEY);
    const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
    if (!Number.isFinite(parsed)) {
      return 320;
    }
    return Math.min(
      RIGHT_PANEL_MAX_WIDTH_PX,
      Math.max(RIGHT_PANEL_MIN_WIDTH_PX, parsed),
    );
  });
  const rightPanelPointerStateRef = useRef<{
    startX: number;
    startWidth: number;
  } | null>(null);
  const contextModelName =
    typeof settings.context.model_name === "string"
      ? settings.context.model_name
      : undefined;
  const { models } = useModels();
  const { user } = useAuth();
  const selectedModel = useMemo(
    () => models.find((model) => model.id === contextModelName),
    [models, contextModelName],
  );
  const selectedThinkingEffort = useMemo(
    () =>
      resolveThinkingEffortForModel(
        selectedModel,
        settings.context.thinking_effort,
      ) ?? "medium",
    [selectedModel, settings.context.thinking_effort],
  );
  const modelThinkingEnabled = useMemo(
    () => selectedModel?.thinking_enabled ?? selectedModel?.supports_thinking ?? false,
    [selectedModel],
  );
  const runtimeModelSpec = useMemo(
    () => getRuntimeModelSpec(selectedModel, selectedThinkingEffort),
    [selectedModel, selectedThinkingEffort],
  );
  useEffect(() => {
    if (!user?.id) {
      setModelPrefsHydrated(false);
      lastPersistedModelPrefsRef.current = "";
      return;
    }
    let cancelled = false;
    setModelPrefsHydrated(false);
    void getUserModelPreferences()
      .then((preferences) => {
        if (cancelled) {
          return;
        }
        const latest = getLocalSettings();
        const nextContext = {
          ...latest.context,
        };
        let changed = false;
        if (
          typeof preferences.model_name === "string" &&
          preferences.model_name.trim().length > 0 &&
          preferences.model_name !== latest.context.model_name
        ) {
          nextContext.model_name = preferences.model_name;
          changed = true;
        }
        if (
          typeof preferences.thinking_effort === "string" &&
          preferences.thinking_effort.trim().length > 0 &&
          preferences.thinking_effort !== latest.context.thinking_effort
        ) {
          nextContext.thinking_effort = preferences.thinking_effort.trim().toLowerCase();
          changed = true;
        }
        if (!nextContext.thinking_effort) {
          nextContext.thinking_effort = "medium";
          changed = true;
        }
        const remoteSignature = JSON.stringify({
          model_name: preferences.model_name ?? null,
          thinking_effort: preferences.thinking_effort ?? null,
        });
        lastPersistedModelPrefsRef.current = remoteSignature;
        if (changed) {
          setSettings("context", nextContext);
        }
      })
      .catch(() => {
        // Keep local settings when remote preferences cannot be loaded.
      })
      .finally(() => {
        if (!cancelled) {
          setModelPrefsHydrated(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [setSettings, user?.id]);

  useEffect(() => {
    if (!user?.id || !modelPrefsHydrated) {
      return;
    }
    const payload = {
      model_name: settings.context.model_name ?? null,
      thinking_effort: selectedThinkingEffort ?? null,
    };
    const signature = JSON.stringify(payload);
    if (signature === lastPersistedModelPrefsRef.current) {
      return;
    }
    const timeout = setTimeout(() => {
      void setUserModelPreferences(payload)
        .then((saved) => {
          lastPersistedModelPrefsRef.current = JSON.stringify({
            model_name: saved.model_name ?? null,
            thinking_effort: saved.thinking_effort ?? null,
          });
        })
        .catch(() => {
          // Keep local state; retry on next change.
        });
    }, 400);
    return () => {
      clearTimeout(timeout);
    };
  }, [
    modelPrefsHydrated,
    selectedThinkingEffort,
    settings.context.model_name,
    user?.id,
  ]);

  const handleSubmit = useSubmitThread({
    isNewThread,
    threadId,
    thread,
    threadContext: {
      ...settings.context,
      model_spec: runtimeModelSpec,
      thinking_effort: selectedThinkingEffort,
      user_id: user?.id,
      thinking_enabled: modelThinkingEnabled || settings.context.mode !== "flash",
      is_plan_mode:
        settings.context.mode === "pro" || settings.context.mode === "ultra",
      subagent_enabled: settings.context.mode === "ultra",
    },
    afterSubmit() {
      if (!isNewThread) {
        void navigate(pathOfThread(threadId!));
      }
    },
  });

  const handleSubmitWithLanding = useCallback(
    (message: Parameters<typeof handleSubmit>[0]) => {
      if (isNewThread && !hasConversation) {
        setHasPendingSubmit(true);
      }
      return handleSubmit(message);
    },
    [handleSubmit, hasConversation, isNewThread],
  );

  // Handle automatic resubmission after truncation and remount
  useEffect(() => {
    if (
      !threadId ||
      isNewThread ||
      thread.isThreadLoading ||
      thread.isLoading ||
      resubmitInFlightThreadRef.current === threadId
    ) {
      return;
    }

    const resubmitKey = `resubmit_${threadId}`;
    const resubmitData = sessionStorage.getItem(resubmitKey);
    if (!resubmitData) return;

    let pending: PendingResubmitData;
    try {
      pending = JSON.parse(resubmitData) as PendingResubmitData;
    } catch (error) {
      console.error("Failed to parse resubmit data:", error);
      sessionStorage.removeItem(resubmitKey);
      setIsTransitioningConversation(false);
      return;
    }

    // Keep pending regenerate payload a bit longer in case thread loading
    // takes time after remount/reconnect.
    if (Date.now() - pending.timestamp >= RESUBMIT_TTL_MS) {
      sessionStorage.removeItem(resubmitKey);
      setIsTransitioningConversation(false);
      return;
    }

    resubmitInFlightThreadRef.current = threadId;
    const timeout = setTimeout(() => {
      void handleSubmit(
        { text: pending.text, files: [] },
        {
          checkpoint: pending.checkpoint ?? undefined,
          // Force a non-resumable run so we don't accidentally continue
          // from stale local resumable events after truncation.
          streamResumable: false,
        },
      )
        .then(() => {
          sessionStorage.removeItem(resubmitKey);
        })
        .catch((error) => {
          const nextAttempts = (pending.attempts ?? 0) + 1;
          console.error(
            `Automatic resubmission failed (attempt ${nextAttempts}):`,
            error,
          );
          if (nextAttempts >= 3) {
            sessionStorage.removeItem(resubmitKey);
            setIsTransitioningConversation(false);
            return;
          }
          sessionStorage.setItem(
            resubmitKey,
            JSON.stringify({
              ...pending,
              attempts: nextAttempts,
            } satisfies PendingResubmitData),
          );
        })
        .finally(() => {
          resubmitInFlightThreadRef.current = null;
        });
    }, RESUBMIT_DELAY_MS);

    return () => {
      clearTimeout(timeout);
      if (resubmitInFlightThreadRef.current === threadId) {
        resubmitInFlightThreadRef.current = null;
      }
    };
  }, [
    threadId,
    isNewThread,
    thread.isThreadLoading,
    thread.isLoading,
    handleSubmit,
  ]);

  // End transition mode as soon as a fresh stream starts.
  useEffect(() => {
    if (isTransitioningConversation && thread.isLoading) {
      setIsTransitioningConversation(false);
    }
  }, [isTransitioningConversation, thread.isLoading]);

  useEffect(() => {
    if (!isNewThread || hasConversation) {
      setHasPendingSubmit(false);
    }
  }, [hasConversation, isNewThread]);

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  const setRightPanelWidthClamped = useCallback((nextWidth: number) => {
    const clamped = Math.min(
      RIGHT_PANEL_MAX_WIDTH_PX,
      Math.max(RIGHT_PANEL_MIN_WIDTH_PX, Math.round(nextWidth)),
    );
    setRightPanelWidth(clamped);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(RIGHT_PANEL_WIDTH_STORAGE_KEY, String(clamped));
    }
  }, []);

  const handleRightPanelResizeStart = useCallback(
    (event: { clientX: number }) => {
      rightPanelPointerStateRef.current = {
        startX: event.clientX,
        startWidth: rightPanelWidth,
      };

      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";

      const onPointerMove = (moveEvent: PointerEvent) => {
        const pointerState = rightPanelPointerStateRef.current;
        if (!pointerState) {
          return;
        }
        // Right panel is anchored on the right; moving left increases width.
        const delta = pointerState.startX - moveEvent.clientX;
        setRightPanelWidthClamped(pointerState.startWidth + delta);
      };

      const cleanup = () => {
        rightPanelPointerStateRef.current = null;
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
      };

      const onPointerUp = () => {
        cleanup();
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp);
    },
    [rightPanelWidth, setRightPanelWidthClamped],
  );

  const truncateAndQueueResubmit = useCallback(
    async (messageId: string, text: string) => {
      if (!threadId) throw new Error("Thread ID is missing");
      setIsTransitioningConversation(true);

      // Stop ongoing stream first to avoid mixed checkpoints.
      if (thread.isLoading) {
        await thread.stop();
        await new Promise((resolve) => setTimeout(resolve, 100));
      }

      const messages = (() => {
        if (thread.messages && thread.messages.length > 0) {
          return thread.messages as Message[];
        }
        if (Array.isArray(thread.values?.messages)) {
          return thread.values.messages as Message[];
        }
        return [] as Message[];
      })();
      const messageIndex = messages.findIndex((m) => m.id === messageId);
      if (messageIndex === -1) throw new Error("Message not found");

      const response = await authFetch(
        `${getBackendBaseURL()}/api/threads/${threadId}/truncate-messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_index: messageIndex }),
        },
      );

      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail ?? "Failed to truncate messages");
      }

      const result = (await response.json()) as TruncateMessagesResponse;
      const checkpoint: ThreadResubmitOptions["checkpoint"] =
        result.checkpoint_id
          ? {
              checkpoint_id: result.checkpoint_id,
              checkpoint_ns: result.checkpoint_ns ?? "",
              checkpoint_map: result.checkpoint_map ?? {},
            }
          : undefined;

      void queryClient.invalidateQueries({
        queryKey: ["threads", "search"],
      });

      sessionStorage.setItem(
        `resubmit_${threadId}`,
        JSON.stringify({
          text,
          timestamp: Date.now(),
          checkpoint,
          attempts: 0,
        } satisfies PendingResubmitData),
      );

      // Force remount so the stream hook reconnects cleanly to latest state.
      const currentCount = parseInt(
        sessionStorage.getItem(`remount_${threadId}`) ?? "0",
        10,
      );
      sessionStorage.setItem(`remount_${threadId}`, String(currentCount + 1));
    },
    [thread, threadId, queryClient],
  );

  const handleEditMessage = useCallback(
    async (messageId: string, newContent: string) => {
      if (isRegenerating) return;
      setIsRegenerating(true);
      try {
        await truncateAndQueueResubmit(messageId, newContent);
      } catch (error) {
        console.error("Failed to edit message:", error);
        setIsTransitioningConversation(false);
      } finally {
        setIsRegenerating(false);
      }
    },
    [isRegenerating, truncateAndQueueResubmit],
  );

  const handleRegenerateMessage = useCallback(
    async (messageId: string, content: string) => {
      if (isRegenerating) return;
      setIsRegenerating(true);
      try {
        await truncateAndQueueResubmit(messageId, content);
      } catch (error) {
        console.error("Failed to regenerate:", error);
        setIsTransitioningConversation(false);
      } finally {
        setIsRegenerating(false);
      }
    },
    [isRegenerating, truncateAndQueueResubmit],
  );

  if (!threadId) {
    return null;
  }

  const threadContextValue = useMemo(
    () => ({ threadId, thread }),
    [threadId, thread],
  );

  return (
    <ThreadContext.Provider value={threadContextValue}>
      <ResizablePanelGroup orientation="horizontal">
        <ResizablePanel
          className="relative"
          defaultSize={artifactPanelOpen ? 46 : 100}
          minSize={artifactPanelOpen ? 30 : 100}
        >
          <div className="bg-dot-grid relative flex size-full min-h-0">
            <header
              className={cn(
                "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center px-4",
                showLanding
                  ? "bg-background/0 backdrop-blur-none"
                  : "bg-background/80 shadow-xs backdrop-blur dark:bg-[rgb(21,21,21)]",
              )}
            >
              <div className="flex w-full items-center justify-between text-sm font-medium">
                <div className="flex items-center">
                  {title !== "Untitled" && (
                    <ThreadTitle threadId={threadId} threadTitle={title} />
                  )}
                  <SessionUsageDisplay usage={thread.values?.token_usage} />
                </div>
                <div className="flex items-center gap-2">
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
                  {!env.IS_ELECTRON && (
                    <Button
                      className="size-7 opacity-50 hover:opacity-100"
                      size="icon"
                      variant="ghost"
                      onClick={() => setTodoPanelOpen(!todoPanelOpen)}
                    >
                      {todoPanelOpen ? (
                        <PanelLeftOpenIcon />
                      ) : (
                        <PanelLeftCloseIcon />
                      )}
                      <span className="sr-only">Toggle todo panel</span>
                    </Button>
                  )}
                </div>
              </div>
            </header>
            <div className="flex min-h-0 w-full">
              <div className="relative flex min-h-0 flex-1 flex-col">
                <main className="flex min-h-0 max-w-full grow flex-col">
                  <div className="flex size-full justify-center">
                    <MessageList
                      className={cn("size-full", !showLanding && "pt-10")}
                      threadId={threadId}
                      isNewThread={isNewThread}
                      thread={thread}
                      paddingBottom={showLanding ? 400 : 160}
                      isRegenerating={isRegenerating}
                      isTransitioning={isTransitioningConversation}
                      onEditMessage={handleEditMessage}
                      onRegenerateMessage={handleRegenerateMessage}
                    />
                  </div>
                </main>
                <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4 pb-6">
                  <div
                    className={cn(
                      "relative w-full",
                      showLanding && "-translate-y-[calc(50vh-200px)]",
                      showLanding ? "max-w-2xl" : "max-w-(--container-width-md)",
                    )}
                  >
                    {/* Welcome section for new threads */}
                    {showLanding && (
                      <div className="mb-8">
                        <Welcome mode={settings.context.mode} />
                      </div>
                    )}

                    {/* Quick actions for new threads */}
                    {showLanding && searchParams.get("mode") !== "skill" && (
                      <div className="mb-4">
                        <QuickActions />
                      </div>
                    )}

                    {/* Input box */}
                    <InputBox
                      className={cn("w-full")}
                      isNewThread={showLanding}
                      autoFocus={showLanding}
                      status={
                        isRegenerating || thread.isLoading
                          ? "streaming"
                          : "ready"
                      }
                      context={settings.context}
                      disabled={
                        env.VITE_STATIC_WEBSITE_ONLY === "true" || isRegenerating
                      }
                      onContextChange={(context) =>
                        setSettings("context", context)
                      }
                      onSubmit={handleSubmitWithLanding}
                      onStop={handleStop}
                    />
                    {env.VITE_STATIC_WEBSITE_ONLY === "true" && (
                      <div className="text-muted-foreground/67 mt-4 w-full text-center text-xs">
                        {t.common.notAvailableInDemoMode}
                      </div>
                    )}
                  </div>
                </div>
              </div>
              {showTodoPanel && (
                <aside
                  className="relative min-h-0 shrink-0 pt-12 pr-4"
                  style={{ width: `${rightPanelWidth}px` }}
                >
                  <button
                    aria-label="Resize right panel"
                    className="hover:after:bg-border absolute inset-y-0 -left-2 z-20 hidden w-4 cursor-col-resize transition-all ease-linear after:absolute after:inset-y-0 after:left-1/2 after:w-[2px] md:block"
                    onPointerDown={handleRightPanelResizeStart}
                    tabIndex={-1}
                    title="Resize panel"
                    type="button"
                  />
                  <div className="flex flex-col gap-3">
                    <TodoList
                      className="mt-4 w-full max-w-[calc(100vw-2rem)]"
                      todos={thread.values.todos ?? []}
                      collapsed={todoListCollapsed}
                      onToggle={() => setTodoListCollapsed(!todoListCollapsed)}
                    />
                    <ContextPanel
                      modelName={contextModelName}
                      subagentEnabled={settings.context.mode === "ultra"}
                    />
                  </div>
                </aside>
              )}
            </div>
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
                    onClick={() => {
                      setArtifactsOpen(false);
                    }}
                  >
                    <XIcon />
                  </Button>
                </div>
                {thread.values.artifacts?.length === 0 ? (
                  <ConversationEmptyState
                    icon={<FilesIcon />}
                    title="No artifact selected"
                    description="Select an artifact to view its details"
                  />
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

/**
 * Resets per-turn usage when the user navigates to a genuinely different thread.
 * Skips the `new` → `{id}` transition so the first turn's usage is preserved.
 */
function UsageResetOnThreadChange({ threadId }: { threadId: string | undefined }) {
  const prevThreadIdRef = useRef(threadId);

  useEffect(() => {
    const prev = prevThreadIdRef.current;
    prevThreadIdRef.current = threadId;
    // Reset only when switching between two real thread IDs (not from "new").
    if (prev && prev !== "new" && threadId && threadId !== "new" && prev !== threadId) {
      resetTurnUsage();
    }
  }, [threadId]);

  return null;
}

export function Chat() {
  const { threadId } = useParams<{ threadId: string }>();
  const [remountCounter, setRemountCounter] = useState(() => {
    // Initialize from sessionStorage if available
    const stored = sessionStorage.getItem(`remount_${threadId}`);
    return stored ? parseInt(stored, 10) : 0;
  });

  // Listen for remount requests
  useEffect(() => {
    const checkRemount = () => {
      const stored = sessionStorage.getItem(`remount_${threadId}`);
      if (stored) {
        const count = parseInt(stored, 10);
        if (count !== remountCounter) {
          setRemountCounter(count);
        }
      }
    };

    const interval = setInterval(checkRemount, 75);
    return () => clearInterval(interval);
  }, [threadId, remountCounter]);

  return (
    <>
      <UsageResetOnThreadChange threadId={threadId} />
      <ChatInner key={`${threadId}-${remountCounter}`} />
    </>
  );
}
