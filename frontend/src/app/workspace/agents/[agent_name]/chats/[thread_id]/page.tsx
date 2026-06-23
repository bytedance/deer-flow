"use client";

import { BotIcon, PlusSquare } from "@/components/ui/icons";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import {
  DEFECT_WORKFLOW_SELECTED_CONTEXT_EVENT,
  DEFECT_WORKFLOW_SELECTED_TASK_STORAGE_PREFIX,
} from "@/components/genui/DefectWorkflowTodoListBlock";
import { Button } from "@/components/ui/button";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import { ChatReportTrigger } from "@/components/workspace/chat-report-trigger";
import {
  CHAT_COMPOSER_INPUT_BOX_CLASSNAME,
  getChatComposerDockClassName,
  getChatComposerFrameClassName,
} from "@/components/workspace/chat-composer-layout";
import { SourceBreadcrumb } from "@/components/workspace/source-breadcrumb";
import { ChatBox, useDeepLinkChat, useThreadChat } from "@/components/workspace/chats";
import { ExportTrigger } from "@/components/workspace/export-trigger";
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
import { Tooltip } from "@/components/workspace/tooltip";
import { useAgent } from "@/core/agents";
import type { DefectWorkflowDeepLinkTarget } from "@/core/defect-workflow";
import { useBlockStore, type UIBlock } from "@/core/genui/store";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings, useThreadSettings } from "@/core/settings";
import { useThreadStream } from "@/core/threads/hooks";
import { textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

const DEFECT_WORKFLOW_CLOSURE_AGENT = "defect-workflow-closure";

type DefectWorkflowSelectedContext = Record<string, unknown>;

function storeDefectWorkflowSelectedTask(threadId: string, selectedTaskId: unknown): void {
  if (typeof window === "undefined") return;
  const key = `${DEFECT_WORKFLOW_SELECTED_TASK_STORAGE_PREFIX}${threadId}`;
  if (selectedTaskId == null) {
    window.sessionStorage.removeItem(key);
    return;
  }
  window.sessionStorage.setItem(key, String(selectedTaskId));
}

function createDefectWorkflowTodoListBlock(
  threadId: string,
  selectedTaskId?: unknown,
  target?: DefectWorkflowDeepLinkTarget | null,
): UIBlock {
  return {
    schema_version: "1.0",
    type: "ui_block",
    action: "create",
    block_id: `${DEFECT_WORKFLOW_CLOSURE_AGENT}:todo-list:${threadId}`,
    component: "defect-workflow-todo-list",
    props: {
      title: "缺陷待办",
      page_size: 20,
      ...(selectedTaskId != null ? { selected_task_id: selectedTaskId } : {}),
      ...(target?.taskId ? { target_task_id: target.taskId } : {}),
      ...(target?.defectId ? { target_defect_id: target.defectId } : {}),
      ...(target?.defectNo ? { target_defect_no: target.defectNo } : {}),
      ...(target?.autoOpen ? { auto_open_detail: true } : {}),
    },
    interactive: false,
    thread_id: threadId,
    metadata: {
      source: "agent-home",
      agent_name: DEFECT_WORKFLOW_CLOSURE_AGENT,
      anchor: "thread-start",
    },
  };
}

function createDefectWorkflowDeepLinkTarget(
  params: Record<string, string>,
): DefectWorkflowDeepLinkTarget | null {
  const taskId = params["task_id"];
  const defectId = params["defect_id"];
  const defectNo = params["defect_no"];
  const autoOpen = params["auto_open"] === "1";
  if (!taskId && !defectId && !defectNo && !autoOpen) return null;
  return {
    taskId,
    defectId,
    defectNo,
    autoOpen,
  };
}

function createDefectWorkflowModelText(
  userText: string,
  context: DefectWorkflowSelectedContext | null,
): string {
  if (!context) return userText;
  return [
    userText,
    "",
    "<defect_workflow_selected_context>",
    JSON.stringify(context, null, 2),
    "</defect_workflow_selected_context>",
    "",
    "请优先基于 defect_workflow_selected_context 回答用户关于当前选中缺陷、任务、设备、节点和表单的问题。不要声称缺少连接器配置；只有当上下文确实没有相关字段时，再说明缺少哪个字段。",
  ].join("\n");
}

export default function AgentChatPage() {
  const { t } = useI18n();
  const [showFollowups, setShowFollowups] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  const { agent_name } = useParams<{
    agent_name: string;
  }>();

  const { agent } = useAgent(agent_name);

  const { threadId, setThreadId, isNewThread, setIsNewThread } =
    useThreadChat();
  const deepLink = useDeepLinkChat(isNewThread);
  const defectWorkflowDeepLinkTarget = useMemo(
    () => createDefectWorkflowDeepLinkTarget(deepLink.passthroughParams),
    [deepLink.passthroughParams],
  );
  const [settings, setSettings] = useThreadSettings(threadId);
  const [localSettings, setLocalSettings] = useLocalSettings();
  const isDefectWorkflowClosureAgent = agent_name === DEFECT_WORKFLOW_CLOSURE_AGENT;
  const selectedDefectWorkflowContextRef = useRef<DefectWorkflowSelectedContext | null>(null);

  const { showNotification } = useNotification();
  const {
    thread,
    sendMessage,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: { ...settings.context, agent_name: agent_name },
    onStart: (createdThreadId) => {
      if (agent_name === DEFECT_WORKFLOW_CLOSURE_AGENT) {
        const store = useBlockStore.getState();
        const selectedTaskId = selectedDefectWorkflowContextRef.current?.taskId;
        storeDefectWorkflowSelectedTask(createdThreadId, selectedTaskId);
        store.setActiveThread(createdThreadId);
        store.upsertBlock(
          createdThreadId,
          createDefectWorkflowTodoListBlock(createdThreadId, selectedTaskId, defectWorkflowDeepLinkTarget),
        );
      }
      setThreadId(createdThreadId);
      setIsNewThread(false);
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(
        null,
        "",
        `/workspace/agents/${agent_name}/chats/${createdThreadId}`,
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

  const autoStartFired = useRef(false);

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      if (isDefectWorkflowClosureAgent) {
        const modelText = createDefectWorkflowModelText(
          message.text.trim(),
          selectedDefectWorkflowContextRef.current,
        );
        void sendMessage(threadId, message, { agent_name }, {
          additionalKwargs: {
            model_text: modelText,
            defect_workflow_context: selectedDefectWorkflowContextRef.current,
          },
        });
        return;
      }

      void sendMessage(threadId, message, { agent_name });
    },
    [sendMessage, threadId, agent_name, isDefectWorkflowClosureAgent],
  );

  useEffect(() => {
    if (!isNewThread || !isDefectWorkflowClosureAgent || deepLink.autoSend) return;

    const store = useBlockStore.getState();
    const selectedTaskId = selectedDefectWorkflowContextRef.current?.taskId;
    if (selectedTaskId == null) {
      storeDefectWorkflowSelectedTask(threadId, null);
    } else {
      storeDefectWorkflowSelectedTask(threadId, selectedTaskId);
    }
    store.setActiveThread(threadId);
    store.upsertBlock(
      threadId,
      createDefectWorkflowTodoListBlock(threadId, selectedTaskId, defectWorkflowDeepLinkTarget),
    );
  }, [isNewThread, isDefectWorkflowClosureAgent, deepLink.autoSend, threadId, defectWorkflowDeepLinkTarget]);

  useEffect(() => {
    if (!isDefectWorkflowClosureAgent) return;

    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        threadId?: string;
        context?: DefectWorkflowSelectedContext | null;
      };
      if (detail.threadId && detail.threadId !== threadId) return;
      if (!detail.context && selectedDefectWorkflowContextRef.current) return;
      selectedDefectWorkflowContextRef.current = detail.context ?? null;
    };

    window.addEventListener(DEFECT_WORKFLOW_SELECTED_CONTEXT_EVENT, handler);
    return () => window.removeEventListener(DEFECT_WORKFLOW_SELECTED_CONTEXT_EVENT, handler);
  }, [isDefectWorkflowClosureAgent, threadId]);

  // Deep-link auto-send: takes precedence over agent auto_start
  useEffect(() => {
    if (!isNewThread || autoStartFired.current) return;

    if (deepLink.autoSend) {
      const allParams = {
        ...(deepLink.source ? { source: deepLink.source } : {}),
        ...(deepLink.context ? { context: deepLink.context } : {}),
        ...deepLink.passthroughParams,
      };

      if (deepLink.prompt) {
        // Deep-link has its own prompt — send immediately
        autoStartFired.current = true;
        void sendMessage(threadId, { text: deepLink.prompt, files: [] }, { agent_name }, { additionalKwargs: allParams });
        return;
      }

      if (Object.keys(deepLink.passthroughParams).length > 0) {
        // Passthrough-only: need agent's auto_start prompt — wait for agent to load
        if (!agent) return; // agent not loaded yet, re-run on next render
        const agentPrompt = agent.starters?.find((s) => s.auto_start)?.prompt;
        if (agentPrompt) {
          autoStartFired.current = true;
          void sendMessage(threadId, { text: agentPrompt, files: [] }, { agent_name }, { additionalKwargs: allParams });
          return;
        }
      }

      // deepLink.autoSend=true but no prompt and no passthrough — fall through to agent auto_start
    }

    // Fallback: agent-configured auto_start
    if (isDefectWorkflowClosureAgent) {
      autoStartFired.current = true;
      return;
    }

    if (!agent) return;
    const autoStarter = agent.starters?.find((s) => s.auto_start);
    if (autoStarter) {
      autoStartFired.current = true;
      void sendMessage(threadId, { text: autoStarter.prompt, files: [] }, { agent_name }, { additionalKwargs: { hide_from_ui: true } });
    }
  }, [isNewThread, agent, sendMessage, threadId, agent_name, deepLink, isDefectWorkflowClosureAgent]);

  // Deep-link pre-fill (when auto_send is not set)
  const promptInputController = usePromptInputController();
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;

  useEffect(() => {
    if (deepLink.source) {
      console.info(`[DeepLink] source=${deepLink.source}`);
    }
  }, [deepLink.source]);

  const lastPreFillRef = useRef<string | null>(null);
  useEffect(() => {
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
  }, [deepLink.autoSend, deepLink.prompt]);

  // Handoff from another agent (e.g. abnormal-judgment → fault-diagnosis)
  const handoffFired = useRef(false);
  useEffect(() => {
    if (!isNewThread || handoffFired.current) return;
    const isHandoff = searchParams.get("handoff") === "1";
    if (!isHandoff) return;

    const key = `handoff:${agent_name}`;
    const raw = sessionStorage.getItem(key);
    if (!raw) return;

    handoffFired.current = true;
    sessionStorage.removeItem(key);

    let handoff: Record<string, unknown>;
    try {
      handoff = JSON.parse(raw);
    } catch {
      return;
    }

    const eq = (handoff.equipment ?? {}) as Record<string, unknown>;
    const events = (handoff.events ?? []) as Array<Record<string, unknown>>;
    const jd = (handoff.judgment ?? {}) as Record<string, unknown>;

    const firstMessage = [
      "---HANDOFF_DATA---",
      JSON.stringify(handoff),
      "---END_HANDOFF_DATA---",
      "",
      `收到异常研判Agent转交：${eq["component_name"] ?? ""} 判定为 ${jd["suspected_fault_type"] ?? "故障"}（置信度 ${Math.round(((jd["confidence"] as number) ?? 0) * 100)}%），请诊断。`,
    ].join("\n");

    void sendMessage(
      threadId,
      { text: firstMessage, files: [] },
      { agent_name },
      { additionalKwargs: { handoff } },
    );
  }, [isNewThread, searchParams, agent_name, sendMessage, threadId]);

  const handleStarterClick = useCallback(
    (prompt: string) => {
      if (isDefectWorkflowClosureAgent) {
        selectedDefectWorkflowContextRef.current = null;
        const store = useBlockStore.getState();
        store.setActiveThread(threadId);
        store.upsertBlock(threadId, createDefectWorkflowTodoListBlock(threadId));
        return;
      }

      handleSubmit({ text: prompt, files: [] });
    },
    [handleSubmit, isDefectWorkflowClosureAgent, threadId],
  );

  useEffect(() => {
    const handler = (e: Event) => {
      const { threadId: eventThreadId, callbackId, payload } = (e as CustomEvent).detail;
      if (eventThreadId !== threadId) return;
      const text = JSON.stringify({ type: "ui_interaction", callback_id: callbackId, payload });
      void sendMessage(threadId, { text, files: [] }, { agent_name }, { additionalKwargs: { hide_from_ui: true } });
    };
    window.addEventListener("genui:interaction-submitted", handler);
    return () => window.removeEventListener("genui:interaction-submitted", handler);
  }, [threadId, sendMessage, agent_name]);

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  const messageListPaddingBottom = showFollowups
    ? MESSAGE_LIST_DEFAULT_PADDING_BOTTOM +
      MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM
    : undefined;
  const showDefectWorkflowLocalHome =
    isNewThread && isDefectWorkflowClosureAgent && !deepLink.autoSend;
  const useNewThreadLayout = isNewThread && !showDefectWorkflowLocalHome;

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ChatBox threadId={threadId}>
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
              {agent?.icon ? (
                <span className="text-sm">{agent.icon}</span>
              ) : (
                <BotIcon className="text-primary h-3.5 w-3.5" />
              )}
              <span className="text-xs font-medium">
                {agent?.display_name ?? agent?.name ?? agent_name}
              </span>
            </div>

            <div className="flex w-full items-center gap-3 text-sm font-medium">
              <SourceBreadcrumb className="shrink-0" />
              <ThreadTitle threadId={threadId} thread={thread} />
            </div>
            <div className="mr-4 flex items-center">
              <TodoCountIndicator />
              <Tooltip content={t.agents.newChat}>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    router.push(`/workspace/agents/${agent_name}/chats/new`);
                  }}
                >
                  <PlusSquare /> {t.agents.newChat}
                </Button>
              </Tooltip>
              <ExportTrigger threadId={threadId} />
              <ChatReportTrigger threadId={threadId} />
              <ArtifactTrigger />
            </div>
          </header>

          <main className="flex min-h-0 max-w-full grow flex-col">
            <div className="flex size-full justify-center">
              <MessageList
                className={cn(
                  "size-full",
                  !useNewThreadLayout && "pt-10",
                  showDefectWorkflowLocalHome && "justify-start",
                )}
                threadId={threadId}
                thread={thread}
                paddingBottom={messageListPaddingBottom}
                hasMoreHistory={hasMoreHistory}
                loadMoreHistory={loadMoreHistory}
                isHistoryLoading={isHistoryLoading}
                agentName={agent_name}
              />
            </div>

            <div className={getChatComposerDockClassName()}>
              <div className={getChatComposerFrameClassName(useNewThreadLayout)}>
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

                <InputBox
                  className={CHAT_COMPOSER_INPUT_BOX_CLASSNAME}
                  isNewThread={useNewThreadLayout}
                  threadId={threadId}
                  autoFocus={useNewThreadLayout}
                  status={
                    thread.error
                      ? "error"
                      : thread.isLoading
                        ? "streaming"
                        : "ready"
                  }
                  context={settings.context}
                  extraHeader={
                    useNewThreadLayout && (
                      <AgentWelcome agent={agent} agentName={agent_name} onStarterClick={handleStarterClick} />
                    )
                  }
                  disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                  onContextChange={(context) => setSettings("context", context)}
                  onFollowupsVisibilityChange={setShowFollowups}
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
      </ChatBox>
    </ThreadContext.Provider>
  );
}
