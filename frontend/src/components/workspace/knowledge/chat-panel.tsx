"use client";

import type { Message } from "@langchain/langgraph-sdk";
import {
  ArrowUpIcon,
  ArrowUpRightIcon,
  CheckIcon,
  ChevronDownIcon,
  HistoryIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { MessageList } from "@/components/workspace/messages";
import { Tooltip } from "@/components/workspace/tooltip";
import { useAgentsApiEnabled } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildKnowledgeScopeSnapshot,
  KNOWLEDGE_SCOPE_KEY,
  localDatasetId,
} from "@/core/knowledge";
import { sourcesForAssistantMessage } from "@/core/knowledge/citations";
import { threadsForKb } from "@/core/knowledge/kb-threads";
import type { KnowledgeBase } from "@/core/knowledge/types";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { useModels } from "@/core/models/hooks";
import { useDeleteThread, useInfiniteThreads, useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";
import { cn } from "@/lib/utils";

import { KbAssistantContent } from "./kb-assistant-content";
import { KbCitationSources } from "./kb-citation-sources";

/** Per-kb composer model memory: `rag-chat-model:{kbId}` → model name. */
const MODEL_STORAGE_PREFIX = "rag-chat-model:";

/**
 * Right-column chat panel bound to the selected knowledge base (spec
 * §4.5/§4.6/§4.7/§5.2). Conversations stay isolated per kb: the stream context
 * carries ``kb_id`` (persisted into ``metadata.kb_id`` on thread creation),
 * the history popover lists only this kb's threads, and the global recent-chat
 * list filters kb threads out (ima-style isolation).
 */
export function KnowledgeChatPanel({
  kb,
  requestedThreadId,
}: {
  kb: KnowledgeBase | null;
  /**
   * External deep-link target: when supplied, apply it as a history-select
   * action once (like clicking a thread in the popover), without overriding
   * user-initiated switches.
   */
  requestedThreadId?: string | null;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.chat;
  // The expand link targets /workspace/agents/rag/..., which the agents layout
  // blocks when the agents API is off — disable the entry instead of landing
  // the user on the "feature not enabled" wall.
  const { enabled: agentsApiEnabled } = useAgentsApiEnabled();
  const kbId = kb?.id ?? null;

  const [threadId, setThreadId] = useState(() => uuid());
  const [isNewThread, setIsNewThread] = useState(true);
    const expandDisabled = isNewThread || !agentsApiEnabled;
  const [draft, setDraft] = useState("");

  // 切库即新对话（还原 `2711a35a2` 的重置，`52b0dd76d` 重构时误删）：
  // 线程只绑定一个库。声明位序必须在下方 requestedThreadId 深链 effect 之前。
  useEffect(() => {
    setThreadId(uuid());
    setIsNewThread(true);
    setDraft("");
  }, [kbId]);

  // Composer model selector: null = unselected → context.model_name stays
  // undefined and the backend resolves request → agent config → global
  // default. A picked model is remembered per kb (localStorage) and read back
  // here, so `rag-chat-model:{kbId}` is the whole memory — nothing else has to
  // agree with it.
  const [pickedModel, setPickedModel] = useState<{
    kbId: string | null;
    name: string;
  } | null>(null);
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();

  // Switching knowledge bases always starts a fresh conversation: threads are
  // bound to exactly one kb via metadata.kb_id and must never bleed across. So
  // the pick is scoped to the kb it was made on (not a bare name that would leak
  // across), and the remembered one is only restored while this build still
  // offers that model — the trigger shows the effective model, so restoring a
  // name the server no longer accepts would make the display lie about what gets
  // sent. Deriving it (rather than an effect) also means it settles by itself
  // once the model list arrives.
  const selectedModelName = useMemo(() => {
    const offered = (name: string | null | undefined) =>
      Boolean(name) && models.some((m) => m.name === name);
    if (pickedModel?.kbId === kbId && offered(pickedModel.name)) {
      return pickedModel.name;
    }
    const remembered = kbId
      ? localStorage.getItem(MODEL_STORAGE_PREFIX + kbId)
      : null;
    return offered(remembered) ? remembered : null;
  }, [pickedModel, kbId, models]);

  // The trigger shows the effective model: the pick (remembered or made here),
  // else the backend's global default (models[0]).
  const activeModel = models.find((m) => m.name === selectedModelName) ?? models[0];

  const handleModelSelect = useCallback(
    (name: string) => {
      setPickedModel({ kbId, name });
      if (kbId) {
        localStorage.setItem(MODEL_STORAGE_PREFIX + kbId, name);
      }
      setModelDialogOpen(false);
    },
    [kbId],
  );

  const context = useMemo(
    () => ({
      model_name: selectedModelName ?? undefined,
      mode: undefined,
      reasoning_effort: undefined,
      agent_name: "rag",
      ...(kbId ? { kb_id: kbId } : {}),
    }),
    [kbId, selectedModelName],
  );

  // Per-message knowledge scope (#5238): one provider-qualified dataset id
  // for the bound kb, display block included for the history summary. The
  // run context above only carries the binding for thread-creation metadata;
  // retrieval reads this snapshot.
  const knowledgeScopeSnapshot = useMemo(
    () =>
      kb
        ? buildKnowledgeScopeSnapshot({
            mode: "selected",
            datasets: [
              {
                id: localDatasetId(kb.id),
                name: kb.name,
                documents: { mode: "all" },
              },
            ],
          })
        : null,
    [kb],
  );

  const {
    thread,
    sendMessage,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context,
    onStart: (createdThreadId) => {
      setThreadId(createdThreadId);
      setIsNewThread(false);
    },
  });

  const threadsQuery = useInfiniteThreads();

  const kbThreads = useMemo(() => {
    if (!kbId) {
      return [];
    }
    const all = threadsQuery.data?.pages.flat() ?? [];
    return threadsForKb(all, kbId);
  }, [threadsQuery.data, kbId]);
  const threadsByDay = useMemo(() => {
    const groups = new Map<string, typeof kbThreads>();
    for (const kbThread of kbThreads) {
      const day = kbThread.updated_at.slice(0, 10);
      groups.set(day, [...(groups.get(day) ?? []), kbThread]);
    }
    return [...groups.entries()];
  }, [kbThreads]);

  const handleNewChat = useCallback(() => {
    setThreadId(uuid());
    setIsNewThread(true);
    setDraft("");
  }, []);
const handleSelectThread = useCallback((nextThreadId: string) => {
    setThreadId(nextThreadId);
    setIsNewThread(false);
  }, []);

  // Apply KB-thread deep link from URL query params (applied ONCE like a popover selection; does not override user-initiated new-chat).
  const appliedThreadRef = useRef<string | null>(null);
  useEffect(() => {
    if (!requestedThreadId || requestedThreadId === appliedThreadRef.current) return;
    appliedThreadRef.current = requestedThreadId;
    handleSelectThread(requestedThreadId);
  }, [requestedThreadId, handleSelectThread]);

  // Same operation logic as the general recent-chat list: useDeleteThread
  // cascades sidecar cleanup + remote delete + local data + query-cache
  // eviction (the history popover re-renders without the row automatically).
  // Deleting the OPEN conversation resets the panel to a fresh chat, mirroring
  // the general list's isCurrentThread handling.
  const { mutate: deleteThread } = useDeleteThread();
  const handleDeleteThread = useCallback(
    (deletedThreadId: string) => {
      const isCurrent = !isNewThread && deletedThreadId === threadId;
      deleteThread({
        threadId: deletedThreadId,
        onDeleted: isCurrent ? handleNewChat : undefined,
      });
    },
    [deleteThread, handleNewChat, isNewThread, threadId],
  );

  const canSend = Boolean(kbId) && draft.trim().length > 0 && !thread.isLoading;
  const handleSubmit = useCallback(() => {
    const text = draft.trim();
    if (!kbId || !text || thread.isLoading) {
      return;
    }
    void sendMessage(
      threadId,
      { text, files: [] },
      undefined,
      knowledgeScopeSnapshot
        ? { additionalKwargs: { [KNOWLEDGE_SCOPE_KEY]: knowledgeScopeSnapshot } }
        : undefined,
    );
    setDraft("");
  }, [draft, kbId, knowledgeScopeSnapshot, sendMessage, thread.isLoading, threadId]);

  const renderMessageFooter = useCallback(
    (message: Message) => {
      if (message.type !== "ai") {
        return null;
      }
      return (
        <KbCitationSources
          kbId={kbId ?? undefined}
          messageId={message.id ?? ""}
          sources={sourcesForAssistantMessage(thread.messages, message.id)}
        />
      );
    },
    [thread.messages, kbId],
  );

  // P2 citation UX (phase-2 batch-1): the answer's [n] markers become
  // superscript CitationMarks once streaming ends (deferred — a half-typed
  // `[` mid-stream never flickers). Human messages stay untouched; surfaces
  // without this prop render plain markdown as before.
  const renderMessageContent = useCallback(
    (message: Message, content: string, isLoading: boolean) => {
      if (message.type !== "ai") {
        return undefined;
      }
      return (
        <KbAssistantContent
          content={content}
          isLoading={isLoading}
          messageId={message.id ?? ""}
          sources={sourcesForAssistantMessage(thread.messages, message.id)}
        />
      );
    },
    [thread.messages],
  );

  // Mirrors the general chat page: answering an ask_clarification interrupt
  // sends a hidden message carrying the structured human_input_response.
  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      let sent = false;
      await sendMessage(
        threadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        { agent_name: "rag" },
        {
          additionalKwargs: {
            hide_from_ui: true,
            human_input_response: response,
            ...(knowledgeScopeSnapshot
              ? { [KNOWLEDGE_SCOPE_KEY]: knowledgeScopeSnapshot }
              : {}),
          },
          onSent: () => {
            sent = true;
          },
        },
      );
      return sent;
    },
    [knowledgeScopeSnapshot, sendMessage, threadId],
  );

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="knowledge-chat-panel">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-3">
        <div className="min-w-0 flex-1 truncate text-sm font-medium">
          {kb?.name ?? ""}
        </div>
        <Tooltip content={tc.newChat}>
          <Button
            aria-label={tc.newChat}
            size="icon-sm"
            variant="ghost"
            onClick={handleNewChat}
          >
            <PlusIcon className="size-4" />
          </Button>
        </Tooltip>
        <DropdownMenu>
          <Tooltip content={tc.history}>
            <DropdownMenuTrigger asChild>
              <Button aria-label={tc.history} size="icon-sm" variant="ghost">
                <HistoryIcon className="size-4" />
              </Button>
            </DropdownMenuTrigger>
          </Tooltip>
          <DropdownMenuContent align="end" className="w-64 overflow-hidden">
            {threadsByDay.length === 0 ? (
              <DropdownMenuLabel>{tc.noHistory}</DropdownMenuLabel>
            ) : (
              /* 历史会话清单（2026-09-08 隐式滑条化）：DropdownMenuContent 基类
                 overflow-y-auto 的老原生竖滑条退役——内容改 overflow-hidden，
                 清单沉进 overlay ScrollArea（type="scroll"、停 2s 淡出）；高度
                 上限 = min(300px 封顶, Radix 可用高减 content p-1 内边距)——
                 触发钮在右栏最顶端，纯可用高上限≈整个界面高（2026-09-25 审查
                 实测 ⇒ 加固定封顶），低视口仍自适应不溢出屏幕（spec §7.4）。 */
              <ScrollArea
                className="max-h-[min(300px,calc(var(--radix-dropdown-menu-content-available-height)-0.5rem))]"
                scrollHideDelay={2000}
                type="scroll"
              >
                <div className="flex flex-col">
                  {threadsByDay.map(([day, dayThreads]) => (
                    <div key={day}>
                      <DropdownMenuLabel>{day}</DropdownMenuLabel>
                      {dayThreads.map((kbThread) => (
                        <DropdownMenuItem
                          key={kbThread.thread_id}
                          className="group/history-item"
                          onClick={() => handleSelectThread(kbThread.thread_id)}
                        >
                          <span className="truncate">
                            {kbThread.values?.title ?? kbThread.thread_id}
                          </span>
                          {/* stopPropagation keeps the row from being selected and
                              the popover open, so several stale conversations can
                              be cleaned up in one go. */}
                          <button
                            aria-label={tc.deleteChat}
                            className="text-muted-foreground hover:text-foreground ml-auto inline-flex size-5 shrink-0 items-center justify-center rounded opacity-0 transition-opacity focus-visible:opacity-100 group-hover/history-item:opacity-100"
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              event.preventDefault();
                              handleDeleteThread(kbThread.thread_id);
                            }}
                          >
                            <Trash2Icon className="size-3.5" />
                          </button>
                        </DropdownMenuItem>
                      ))}
                    </div>
                  ))}
                </div>
              </ScrollArea>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <Tooltip content={agentsApiEnabled ? tc.expandToFullPage : tc.expandDisabledAgentsOff}>
          {/* The span stays hoverable so the tooltip still shows while the
              link itself is pointer-events-none (disabled). */}
          <span className="inline-flex">
            <Link
              aria-disabled={expandDisabled}
              aria-label={tc.expandToFullPage}
              className={cn(
                "hover:bg-accent hover:text-accent-foreground inline-flex size-8 items-center justify-center rounded-md",
                expandDisabled && "pointer-events-none opacity-50",
              )}
              href={expandDisabled ? "#" : `/workspace/agents/rag/chats/${threadId}`}
            >
              <ArrowUpRightIcon className="size-4" />
            </Link>
          </span>
        </Tooltip>
      </header>

      <div className="relative min-h-0 flex-1">
        {kb ? (
          <MessageList
            className="size-full"
            threadId={threadId}
            thread={thread}
            hasMoreHistory={hasMoreHistory}
            loadMoreHistory={loadMoreHistory}
            isHistoryLoading={isHistoryLoading}
            renderMessageContent={renderMessageContent}
            renderMessageFooter={renderMessageFooter}
            onSubmitHumanInput={handleSubmitHumanInput}
          />
        ) : (
          <div className="text-muted-foreground flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
            <div className="text-sm font-medium">{t.knowledge.selectKbTitle}</div>
            <div className="text-xs">{t.knowledge.selectKbHint}</div>
          </div>
        )}
      </div>

      {/* Composer styled after the home-page InputBox: one rounded container
          holds the textarea, the deep-retrieval toggle, and the send button. */}
      <div className="shrink-0 border-t p-3">
        <div className="focus-within:border-ring focus-within:ring-ring/50 rounded-xl border bg-white/80 shadow-xs transition-colors focus-within:ring-[3px] dark:bg-background/80">
          <Textarea
            className="max-h-32 min-h-14 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
            disabled={!kb || thread.isLoading}
            placeholder={tc.inputPlaceholder}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                handleSubmit();
              }
            }}
          />
          <div className="flex items-center justify-between gap-2 px-2 pb-2">
            <div className="flex min-w-0 items-center gap-2">
              <ModelSelector open={modelDialogOpen} onOpenChange={setModelDialogOpen}>
                <ModelSelectorTrigger asChild>
                  <button
                    aria-label={tc.selectModel}
                    className="text-muted-foreground hover:text-foreground flex min-w-0 max-w-40 items-center gap-1 rounded-md px-1.5 py-1 text-xs transition-colors disabled:pointer-events-none disabled:opacity-50"
                    disabled={!kb || models.length === 0}
                    type="button"
                  >
                    <span className="truncate">{activeModel?.display_name ?? activeModel?.name ?? tc.selectModel}</span>
                    <ChevronDownIcon className="size-3 shrink-0" />
                  </button>
                </ModelSelectorTrigger>
                <ModelSelectorContent title={tc.selectModel}>
                  <ModelSelectorInput placeholder={tc.searchModels} />
                  <ModelSelectorList>
                    {models.map((m) => (
                      <ModelSelectorItem
                        key={m.name}
                        value={m.name}
                        onSelect={() => handleModelSelect(m.name)}
                      >
                        <div className="flex min-w-0 flex-1 flex-col">
                          <ModelSelectorName>{m.display_name ?? m.name}</ModelSelectorName>
                          <span className="text-muted-foreground truncate text-[10px]">{m.model}</span>
                        </div>
                        {m.name === selectedModelName ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </ModelSelectorItem>
                    ))}
                  </ModelSelectorList>
                </ModelSelectorContent>
              </ModelSelector>
            </div>
            <Tooltip content={tc.send}>
              {/* The span keeps the tooltip reachable while the button is disabled */}
              <span className="inline-flex">
                <Button
                  aria-label={tc.send}
                  className="rounded-full"
                  disabled={!canSend}
                  size="icon-sm"
                  onClick={handleSubmit}
                >
                  <ArrowUpIcon className="size-4" />
                </Button>
              </span>
            </Tooltip>
          </div>
        </div>
      </div>
    </div>
  );
}
