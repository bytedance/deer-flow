"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type PromptInputMessage,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import {
  CHAT_COMPOSER_INPUT_BOX_CLASSNAME,
  getChatComposerDockClassName,
  getChatComposerFrameClassName,
} from "@/components/workspace/chat-composer-layout";
import { ChatReportTrigger } from "@/components/workspace/chat-report-trigger";
import {
  ChatBox,
  useDeepLinkChat,
  useSpecificChatMode,
  useThreadChat,
} from "@/components/workspace/chats";
import { GreetingCard } from "@/components/workspace/chats/greeting-card";
import { ExportTrigger } from "@/components/workspace/export-trigger";
import { IndustrialOnboardingOverlay } from "@/components/workspace/industrial-onboarding-overlay";
import { InputBox } from "@/components/workspace/input-box";
import {
  MessageList,
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM,
} from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { SourceBreadcrumb } from "@/components/workspace/source-breadcrumb";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoCountIndicator } from "@/components/workspace/todo-count-indicator";
import { TodoList } from "@/components/workspace/todo-list";
import { Welcome } from "@/components/workspace/welcome";
import { useGreeting } from "@/core/greeting/use-greeting";
import {
  getLaunchThread,
  setLaunchThread,
} from "@/core/deep-link/launch-session";
import {
  EHM_VIEWPORT_RESUME_EVENT,
  syncRouteToParent,
} from "@/core/auth/ehm-host-bridge";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useThreadSettings } from "@/core/settings";
import { useThreadStream } from "@/core/threads/hooks";
import { textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  const { t } = useI18n();
  const [showFollowups, setShowFollowups] = useState(false);
  const [layoutEpoch, setLayoutEpoch] = useState(0);
  const { threadId, setThreadId, isNewThread, setIsNewThread, isMock } =
    useThreadChat();
  const [settings, setSettings] = useThreadSettings(threadId);
  const mountedRef = useRef(false);
  useSpecificChatMode();
  const deepLink = useDeepLinkChat(isNewThread);
  const launchRouteKey = "chat";
  const restoredLaunchThreadId =
    isNewThread && deepLink.launchId
      ? getLaunchThread(deepLink.launchId, launchRouteKey)
      : null;

  useEffect(() => {
    mountedRef.current = true;
  }, []);

  useEffect(() => {
    const handleViewportResume = () => {
      window.dispatchEvent(new Event("resize"));
      setLayoutEpoch((value) => value + 1);
    };
    window.addEventListener(EHM_VIEWPORT_RESUME_EVENT, handleViewportResume);
    return () =>
      window.removeEventListener(
        EHM_VIEWPORT_RESUME_EVENT,
        handleViewportResume,
      );
  }, []);

  const { showNotification } = useNotification();

  const {
    thread,
    sendMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: settings.context,
    isMock,
    onSend: (_threadId) => {
      setThreadId(_threadId);
      setIsNewThread(false);
    },
    onStart: (createdThreadId) => {
      if (deepLink.launchId) {
        setLaunchThread(deepLink.launchId, createdThreadId, launchRouteKey);
      }
      setThreadId(createdThreadId);
      setIsNewThread(false);
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(null, "", `/workspace/chats/${createdThreadId}`);
      syncRouteToParent({
        routePath: `/workspace/chats/${createdThreadId}`,
        threadId: createdThreadId,
        isNewThread: false,
      });
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

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      void sendMessage(threadId, message);
    },
    [sendMessage, threadId],
  );

  const { greeting, isLoading: isGreetingLoading } = useGreeting(
    threadId,
    isNewThread,
  );

  useEffect(() => {
    if (!isNewThread || !restoredLaunchThreadId) return;
    setThreadId(restoredLaunchThreadId);
    setIsNewThread(false);
    history.replaceState(
      null,
      "",
      `/workspace/chats/${restoredLaunchThreadId}`,
    );
    syncRouteToParent({
      routePath: `/workspace/chats/${restoredLaunchThreadId}`,
      threadId: restoredLaunchThreadId,
      isNewThread: false,
    });
  }, [isNewThread, restoredLaunchThreadId, setThreadId, setIsNewThread]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const routePath = isNewThread
      ? `/workspace/chats/new${window.location.search || ""}`
      : `/workspace/chats/${threadId}`;
    syncRouteToParent({
      routePath,
      threadId: isNewThread ? undefined : threadId,
      isNewThread,
    });
  }, [
    deepLink.autoSend,
    deepLink.launchId,
    deepLink.prompt,
    isNewThread,
    threadId,
  ]);

  useEffect(() => {
    const handler = (e: Event) => {
      const {
        threadId: eventThreadId,
        callbackId,
        payload,
      } = (e as CustomEvent).detail;
      if (eventThreadId !== threadId) return;
      const text = JSON.stringify({
        type: "ui_interaction",
        callback_id: callbackId,
        payload,
      });
      void sendMessage(threadId, { text, files: [] }, undefined, {
        additionalKwargs: { hide_from_ui: true },
      });
    };
    window.addEventListener("genui:interaction-submitted", handler);
    return () =>
      window.removeEventListener("genui:interaction-submitted", handler);
  }, [threadId, sendMessage]);

  // Deep-link auto-send
  const deepLinkFiredRef = useRef(false);
  const promptInputController = usePromptInputController();
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;

  useEffect(() => {
    if (deepLink.source) {
      console.info(`[DeepLink] source=${deepLink.source}`);
    }
  }, [deepLink.source]);

  useEffect(() => {
    if (restoredLaunchThreadId) return;
    if (!deepLink.autoSend || !deepLink.prompt || deepLinkFiredRef.current)
      return;
    deepLinkFiredRef.current = true;
    const allParams = {
      ...(deepLink.source ? { source: deepLink.source } : {}),
      ...(deepLink.context ? { context: deepLink.context } : {}),
      ...deepLink.passthroughParams,
    };
    void sendMessage(
      threadId,
      { text: deepLink.prompt, files: [] },
      undefined,
      { additionalKwargs: allParams },
    );
  }, [
    deepLink.autoSend,
    deepLink.prompt,
    deepLink.source,
    deepLink.context,
    deepLink.passthroughParams,
    threadId,
    sendMessage,
    restoredLaunchThreadId,
  ]);

  // Deep-link pre-fill (when auto_send is not set)
  const lastPreFillRef = useRef<string | null>(null);
  useEffect(() => {
    if (restoredLaunchThreadId) return;
    if (deepLink.autoSend) return;
    const text = deepLink.prompt;
    if (!text || text === lastPreFillRef.current) return;
    lastPreFillRef.current = text;
    const timer = setTimeout(() => {
      setInputRef.current(text);
      const textarea = document.querySelector("textarea");
      if (textarea) {
        textarea.focus();
        textarea.selectionStart = textarea.value.length;
        textarea.selectionEnd = textarea.value.length;
      }
    }, 100);
    return () => clearTimeout(timer);
  }, [deepLink.autoSend, deepLink.prompt, restoredLaunchThreadId]);

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  const messageListPaddingBottom = showFollowups
    ? MESSAGE_LIST_DEFAULT_PADDING_BOTTOM +
      MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM
    : undefined;

  return (
    <>
      <ThreadContext.Provider value={{ thread, isMock }}>
        <ChatBox key={`${threadId}:${layoutEpoch}`} threadId={threadId}>
          <div className="relative flex size-full min-h-0 justify-between">
            <header
              className={cn(
                "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center px-4",
                isNewThread
                  ? "bg-background/0 backdrop-blur-none"
                  : "bg-background/80 shadow-xs backdrop-blur",
              )}
            >
              <div className="flex w-full items-center gap-3 text-sm font-medium">
                <SourceBreadcrumb className="shrink-0" />
                <ThreadTitle threadId={threadId} thread={thread} />
              </div>
              <div className="flex items-center gap-2">
                <TodoCountIndicator />
                <ExportTrigger threadId={threadId} />
                <ChatReportTrigger threadId={threadId} />
                <ArtifactTrigger />
              </div>
            </header>
            <main className="flex min-h-0 max-w-full grow flex-col">
              <div className="flex size-full justify-center">
                <MessageList
                  className={cn("size-full", !isNewThread && "pt-10")}
                  threadId={threadId}
                  thread={thread}
                  paddingBottom={messageListPaddingBottom}
                  hasMoreHistory={hasMoreHistory}
                  loadMoreHistory={loadMoreHistory}
                  isHistoryLoading={isHistoryLoading}
                  agentName={settings.context.agent_name as string | undefined}
                />
              </div>
              <div className={getChatComposerDockClassName(isNewThread)}>
                <div
                  className={cn(
                    getChatComposerFrameClassName(isNewThread),
                    isNewThread &&
                      "flex min-h-[clamp(22rem,55vh,34rem)] flex-col justify-center",
                  )}
                >
                  <div className="absolute -top-4 right-0 left-0 z-0">
                    <div className="absolute right-0 bottom-0 left-0">
                      <TodoList
                        className="bg-background/5"
                        todos={thread.values.todos ?? []}
                        hidden={
                          !thread.values.todos ||
                          thread.values.todos.length === 0
                        }
                      />
                    </div>
                  </div>
                  {mountedRef.current ? (
                    <InputBox
                      className={CHAT_COMPOSER_INPUT_BOX_CLASSNAME}
                      isNewThread={isNewThread}
                      threadId={threadId}
                      autoFocus={isNewThread}
                      status={
                        thread.error
                          ? "error"
                          : thread.isLoading
                            ? "streaming"
                            : "ready"
                      }
                      context={settings.context}
                      extraHeader={
                        isNewThread &&
                        (greeting ? (
                          <GreetingCard
                            greeting={greeting.greeting}
                            isLoading={isGreetingLoading}
                          />
                        ) : (
                          <Welcome mode={settings.context.mode} />
                        ))
                      }
                      disabled={
                        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                        isUploading
                      }
                      onContextChange={(context) =>
                        setSettings("context", context)
                      }
                      onFollowupsVisibilityChange={setShowFollowups}
                      onSubmit={handleSubmit}
                      onStop={handleStop}
                    />
                  ) : (
                    <div
                      aria-hidden="true"
                      className={cn(
                        "bg-background/5 h-32 w-full -translate-y-4 rounded-2xl",
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
      </ThreadContext.Provider>
      <IndustrialOnboardingOverlay />
    </>
  );
}
