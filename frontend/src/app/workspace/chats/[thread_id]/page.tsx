"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import { ChatReportTrigger } from "@/components/workspace/chat-report-trigger";
import { SourceBreadcrumb } from "@/components/workspace/source-breadcrumb";
import {
  ChatBox,
  useSpecificChatMode,
  useThreadChat,
} from "@/components/workspace/chats";
import { GreetingCard } from "@/components/workspace/chats/greeting-card";
import {
  CHAT_COMPOSER_INPUT_BOX_CLASSNAME,
  getChatComposerDockClassName,
  getChatComposerFrameClassName,
} from "@/components/workspace/chat-composer-layout";
import { ExportTrigger } from "@/components/workspace/export-trigger";
import { IndustrialOnboardingOverlay } from "@/components/workspace/industrial-onboarding-overlay";
import { InputBox } from "@/components/workspace/input-box";
import {
  MessageList,
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM,
} from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { TodoCountIndicator } from "@/components/workspace/todo-count-indicator";
import { Welcome } from "@/components/workspace/welcome";
import { useGreeting } from "@/core/greeting/use-greeting";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings, useThreadSettings } from "@/core/settings";
import { useThreadStream } from "@/core/threads/hooks";
import { textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  const { t } = useI18n();
  const [showFollowups, setShowFollowups] = useState(false);
  const { threadId, setThreadId, isNewThread, setIsNewThread, isMock } =
    useThreadChat();
  const [settings, setSettings] = useThreadSettings(threadId);
  const [localSettings, setLocalSettings] = useLocalSettings();
  const mountedRef = useRef(false);
  useSpecificChatMode();

  useEffect(() => {
    mountedRef.current = true;
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
      setThreadId(createdThreadId);
      setIsNewThread(false);
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(null, "", `/workspace/chats/${createdThreadId}`);
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

  const handleSuggestionClick = useCallback(
    (suggestion: string) => {
      void sendMessage(threadId, { text: suggestion, files: [] });
    },
    [sendMessage, threadId],
  );

  useEffect(() => {
    const handler = (e: Event) => {
      const { threadId: eventThreadId, callbackId, payload } = (e as CustomEvent).detail;
      if (eventThreadId !== threadId) return;
      const text = JSON.stringify({ type: "ui_interaction", callback_id: callbackId, payload });
      void sendMessage(threadId, { text, files: [] }, undefined, { additionalKwargs: { hide_from_ui: true } });
    };
    window.addEventListener("genui:interaction-submitted", handler);
    return () => window.removeEventListener("genui:interaction-submitted", handler);
  }, [threadId, sendMessage]);
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
      <ChatBox threadId={threadId}>
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
            <div className={getChatComposerDockClassName()}>
              <div className={getChatComposerFrameClassName(isNewThread)}>
                <div className="absolute -top-4 right-0 left-0 z-0">
                  <div className="absolute right-0 bottom-0 left-0">
                    <TodoList
                      className="bg-background/5"
                      todos={thread.values.todos ?? []}
                      hidden={
                        !thread.values.todos || thread.values.todos.length === 0
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
                          suggestions={greeting.suggestions}
                          isLoading={isGreetingLoading}
                          onSuggestionClick={handleSuggestionClick}
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
