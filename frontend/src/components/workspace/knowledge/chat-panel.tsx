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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { MessageList } from "@/components/workspace/messages";
import { Tooltip } from "@/components/workspace/tooltip";
import { useAgentsApiEnabled } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { latestGraphTraceTurn, latestRetrievalTurn, parseGraphSearchTrace, sourcesForAssistantMessage } from "@/core/knowledge/citations";
import { threadsForKb } from "@/core/knowledge/kb-threads";
import type { GraphRetrievalTrace, GraphRetrievalOverlay, KnowledgeBase } from "@/core/knowledge/types";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { getMessageCopyData } from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import { useRegisterActivity } from "@/core/threads/activity-context";
import { useDeleteThread, useInfiniteThreads, useThreadStream } from "@/core/threads/hooks";
import { pathOfKnowledgeThread, pathOfThread } from "@/core/threads/utils";
import { uuid } from "@/core/utils/uuid";
import { cn } from "@/lib/utils";

import { ChunkTickRail } from "./chunk-tick-rail";
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
  onOpenWikiEntry,
  onRetrievalOverlay,
  onGraphOverlay,
  requestedThreadId,
}: {
  kb: KnowledgeBase | null;
  /** Wiki citation cards open the entry drawer (overlay) via this page-held callback. */
  onOpenWikiEntry?: (entryId: string) => void;
  /**
   * P6 检索联动（spec §9 通道二）：每完成一轮含引用的对话，把「提问文本 +
   * 引用 chunk_id 列表」上报 page 层供向量空间叠加。零后端取数——复用
   * sourcesForAssistantMessage 的既有解析。
   */
  onRetrievalOverlay?: (VectorRetrievalOverlay) => void;
  /**
   * P4 图谱路径高亮（2026-08-19 spec §7）：每完成一轮含 graph_search 轨迹的
   * 对话，把「提问文本 + 三层检索轨迹」上报 page 层供知识图谱叠加。与向量
   * 通道同节奏（同按 answer id 去重、流式进行中不上报）。
   */
  onGraphOverlay?: (overlay: GraphRetrievalOverlay) => void;
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
  const [deepResearch, setDeepResearch] = useState(false);
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
      deep_research: deepResearch,
    }),
    [kbId, deepResearch, selectedModelName],
  );

  /** 本线程内收到的实时检索轨迹缓存（tool_call_id → trace）；切线程即清空。
      spec §7 实时旁路：工具输出预算可能把超大 graph_search ToolMessage 替换成
      摘要预览（消息解析不出 trace），这里按 tool_call_id 缓存 custom 事件
      （graph_retrieval_trace）送达的轨迹副本，供图谱上报兜底；重载路径走
      journal 全文解析，不经过本通道。 */
  const graphTraceEventsRef = useRef(new Map<string, GraphRetrievalTrace>());
  useEffect(() => {
    graphTraceEventsRef.current.clear();
  }, [threadId]);

  const {
    thread,
    liveRunId,
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
    onStreamCustomEvent: (event) => {
      if (!event || typeof event !== "object") return;
      const record = event as { type?: unknown; tool_call_id?: unknown; trace?: unknown };
      if (record.type !== "graph_retrieval_trace" || typeof record.tool_call_id !== "string") return;
      const trace = parseGraphSearchTrace({ trace: record.trace });
      if (trace) {
        graphTraceEventsRef.current.set(record.tool_call_id, trace);
      }
    },
  });

  // 知识库面板也注册(2026-09-12 用户裁决「跟」):它有自己的 kb 绑定线程,不跟的话,
  // 在这聊天时 app 的灯会显示主线程那条可能一直 idle 的线程,看起来像坏了。
  // href 必须是 knowledge 路由:从 threadId 反推进会落到 chats 路由,而那里的 rag
  // agent 没有 kb 绑定,检索永不触发(§5.2)。
  useRegisterActivity(
    isNewThread
      ? null
      : {
          threadId,
          runId: liveRunId,
          href: kbId
            ? pathOfKnowledgeThread(kbId, threadId)
            : pathOfThread(threadId),
        },
  );

  const threadsQuery = useInfiniteThreads();

  // P6 检索联动上报（spec §9 通道二）：对话每完成一轮（含引用时）上报一次，
  // 按 ai message id 去重——流式 token 追加引发的重复渲染不会重复上报；
  // 流式进行中（isLoading）不上报，等该轮落定。
  const lastReportedTurnRef = useRef<string | null>(null);
  useEffect(() => {
    if (!onRetrievalOverlay || thread.isLoading) {
      return;
    }
    const turn = latestRetrievalTurn(thread.messages);
    if (!turn || turn.messageId === lastReportedTurnRef.current) {
      return;
    }
    lastReportedTurnRef.current = turn.messageId;
    onRetrievalOverlay({
      source: "chat",
      text: turn.text,
      hits: turn.citations.map((citation) => ({ pointId: citation.chunk_id, score: citation.score })),
    });
  }, [thread.messages, thread.isLoading, onRetrievalOverlay]);

  // P4 图谱检索轨迹上报（spec §7）：与向量通道同节奏——每完成一轮含
  // graph_search 轨迹的对话上报一次，按 ai message id 去重（流式 token 追加
  // 不重复上报；流式进行中不上报，等该轮落定）。
  const lastReportedGraphTurnRef = useRef<string | null>(null);
  useEffect(() => {
    if (!onGraphOverlay || thread.isLoading) {
      return;
    }
    const turn = latestGraphTraceTurn(thread.messages, graphTraceEventsRef.current);
    if (!turn || turn.messageId === lastReportedGraphTurnRef.current) {
      return;
    }
    lastReportedGraphTurnRef.current = turn.messageId;
    onGraphOverlay({ source: "chat", text: turn.text, trace: turn.trace });
  }, [thread.messages, thread.isLoading, onGraphOverlay]);
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
        onRemoteDeleted: isCurrent ? handleNewChat : undefined,
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
    void sendMessage(threadId, { text, files: [] });
    setDraft("");
  }, [draft, kbId, sendMessage, thread.isLoading, threadId]);

  const renderMessageFooter = useCallback(
    (message: Message) => {
      if (message.type !== "ai") {
        return null;
      }
      return (
        <KbCitationSources
          kbId={kbId ?? undefined}
          messageId={message.id ?? ""}
          onOpenWikiEntry={onOpenWikiEntry}
          sources={sourcesForAssistantMessage(thread.messages, message.id)}
        />
      );
    },
    [thread.messages, onOpenWikiEntry, kbId],
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

  // ── 会话刻度轨（2026-09-08，文档详情切片刻度轨同款方案）──────────
  // 刻度内容 = 用户问的问题：连续 human 消息同属一个 turn（与 MessageList
  // human 组分组同口径），一轮一刻度；preview 取问题文本首行
  // （getMessageCopyData 已剥 uploaded-files 标签）。
  const questions = useMemo(() => {
    const runs: string[] = [];
    thread.messages.forEach((message, index) => {
      if (message.type !== "human") return;
      const firstLine = (getMessageCopyData(message) ?? "").split("\n")[0] ?? "";
      if (thread.messages[index - 1]?.type === "human" && runs.length > 0) {
        runs[runs.length - 1] = `${runs[runs.length - 1]} ${firstLine}`.trim();
      } else {
        runs.push(firstLine);
      }
    });
    return runs;
  }, [thread.messages]);

  const tickEntries = useMemo(
    () =>
      questions.map((preview, index) => ({
        index,
        preview: preview === "" ? null : preview,
      })),
    [questions],
  );

  const [activeQuestion, setActiveQuestion] = useState(0);
  const messageZoneRef = useRef<HTMLDivElement | null>(null);

  // active 追踪：顶边越过视口 40% 线的最后一个刻度为当前刻度；全局序号来自
  // data-human-turn（虚拟化窗口化后仍可读）。
  useEffect(() => {
    const vp = messageZoneRef.current?.querySelector(
      "[data-slot='scroll-area-viewport']",
    );
    if (!vp || questions.length === 0) return;
    let frame = 0;
    const compute = () => {
      const middle = vp.getBoundingClientRect().top + vp.clientHeight * 0.4;
      const nodes = vp.querySelectorAll("[data-human-turn]");
      let next = 0;
      let found = false;
      nodes.forEach((node) => {
        if (node.getBoundingClientRect().top <= middle) {
          next = Number(node.getAttribute("data-human-turn"));
          found = true;
        }
      });
      if (!found && nodes.length > 0) {
        next = Number(nodes[0]?.getAttribute("data-human-turn"));
      }
      const clamped = Math.min(Math.max(next, 0), questions.length - 1);
      setActiveQuestion((prev) => (prev === clamped ? prev : clamped));
    };
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        compute();
      });
    };
    compute();
    vp.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      vp.removeEventListener("scroll", onScroll);
    };
  }, [threadId, questions.length]);

  // 刻度点击跳转：目标在渲染窗口内直接精滚；虚拟化（≥60 组）窗口外先按比例
  // 落点附近，再按已渲染节点全局序号估步长逐步收敛（封顶 6 步），目标进窗后
  // 精滚落定。
  const jumpToQuestion = useCallback(
    (index: number) => {
      const vp = messageZoneRef.current?.querySelector(
        "[data-slot='scroll-area-viewport']",
      );
      if (!vp) return;
      const scrollToNode = (node: Element) => {
        const top =
          vp.scrollTop +
          (node.getBoundingClientRect().top - vp.getBoundingClientRect().top) -
          16;
        vp.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      };
      const direct = vp.querySelector(`[data-human-turn="${index}"]`);
      if (direct) {
        scrollToNode(direct);
        return;
      }
      let steps = 0;
      const converge = () => {
        const node = vp.querySelector(`[data-human-turn="${index}"]`);
        if (node) {
          scrollToNode(node);
          return;
        }
        if (++steps > 6) return;
        const nodes = [...vp.querySelectorAll("[data-human-turn]")];
        if (nodes.length === 0) return;
        const first = nodes[0]!;
        const last = nodes[nodes.length - 1]!;
        const oFirst = Number(first.getAttribute("data-human-turn"));
        const oLast = Number(last.getAttribute("data-human-turn"));
        const per =
          oLast > oFirst
            ? Math.max(
                80,
                (last.getBoundingClientRect().top -
                  first.getBoundingClientRect().top) /
                  (oLast - oFirst),
              )
            : 176;
        const before = index < oFirst;
        const anchorOrd = before ? oFirst : oLast;
        vp.scrollTop += (index - anchorOrd) * per;
        requestAnimationFrame(converge);
      };
      vp.scrollTop =
        ((index + 0.5) / Math.max(1, questions.length)) *
        Math.max(0, vp.scrollHeight - vp.clientHeight);
      requestAnimationFrame(converge);
    },
    [questions.length],
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

      <div className="relative min-h-0 flex-1" ref={messageZoneRef}>
        {kb ? (
          <>
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
            {/* 会话刻度轨（2026-09-08）：文档详情切片刻度轨同款方案——右缘刻度
                脊 + 悬浮弹窗左侧标签层，刻度内容换为用户问题；overlay 层不进
                消息滚动流。 */}
            <ChunkTickRail
              active={activeQuestion}
              entries={tickEntries}
              onJump={jumpToQuestion}
              tickLabel={tc.questionTickAria}
              total={questions.length}
              unloadedLabel={tc.questionTickEmpty}
            />
          </>
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
              <Tooltip content={tc.deepResearchHint}>
                <label className="text-muted-foreground flex shrink-0 cursor-pointer items-center gap-1.5 text-xs">
                  <Switch
                    checked={deepResearch}
                    className="shrink-0"
                    disabled={!kb}
                    onCheckedChange={setDeepResearch}
                  />
                  <span className="whitespace-nowrap">{tc.deepResearch}</span>
                </label>
              </Tooltip>
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
