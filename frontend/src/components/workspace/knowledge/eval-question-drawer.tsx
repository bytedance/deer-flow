"use client";

/**
 * 考题详情 drawer（2026-08-27 spec §4.5，plan Task 6；2026-09-08 裸奔退役
 * 重设计；2026-10-06 改锚对升级，spec §2①/③）：Sheet 右侧覆盖式（EvalRunDrawer
 * 同款），只读展示完整字段。容器化沿用图谱实体抽屉定案配方（09-05：bg-card +
 * border + rounded-lg + shadow-xs 卡 + 卡内分组头带 border-b）：
 * - sticky 紧凑头：query 作标题（line-clamp-2）承载身份，泛称「考题详情」
 *   沉 sr-only 描述（项目 Sheet 配方）；分类/预期路径芯片行随头不随滚；
 * - 参考答案卡 / 参考文档卡 / 实体卡（仅有值显，Waypoints 图谱路词汇）；
 * - 动作栏在 ScrollArea 外（SheetContent flex 列：滚动区 flex-1 + footer
 *   shrink-0 border-t）——复现主/删除次钉底，不随滚、短内容不悬空。
 * 参考文档卡（2026-10-06 升级）：「文档名+序号徽章」→ 逐片**只读** ChunkCard
 * （不传 onEdit/onDelete/onReExtract，与改锚编辑态避免两套编辑口）；一次
 * listChunksByIds 同时供正文预览与悬空判定（请求集 − 返回集 = 悬空，服务端
 * 静默丢缺片）；序号徽章保留（chunk id 稳定身份，非切片抽屉位置序）；悬空的
 * 片单列一行警示（序号徽章 + 「悬空」词），编辑态同样单列且带勾选框——摘除
 * 是悬空锚唯一的出路，缺这行草稿就永远带着缺片、missing_chunk 恒拦。只读态
 * 只显已锚定的片。
 * 片级折叠（2026-10-06 甲）：#序号行升级折叠触发行（ChevronDown，勾选区组头
 * 同款），收起显 chunkPreview 两行摘要、**默认全收起**（这面用途是扫锚了哪几
 * 片），展开才落整张 ChunkCard；摘要行与编辑勾选区逐字同口径，悬空行不折。
 * 疑片「存疑」徽章（Task 5，spec §2④）：随触发行可见（收起态不藏展开区），
 * 行悬浮=Tooltip 机器依据（AnchorBlockNotice 只读形态）。
 * 「编辑锚定」入口（spec §2③）：按文档折叠分组勾选区——组头 = 文档名 +
 * 「已选 n/N」（实时）、默认收起（含已锚片的文档默认展开）、组内 = 该文档
 * 全部切片（内容摘要行 + 勾选框，已锚默认勾上）、组内分页 50/页加载更多
 * （listDocumentChunks）、勾后可整组收起。清空勾选 = 解除锚定（允许）。保存
 * 走 B′ 锚定核验（keyed=question.id，useAnchorConfirm + AnchorBlockNotice）：
 * 原「保存」永不带 anchor_ack（盲双击不落库），红块「仍要保存」才以
 * anchor_ack=true 重提；missing_chunk 不可覆盖（无确认钮）。改锚只动锚——
 * 题面/分类/预期路径/参考答案的编辑仍不支持（§4.2 规则 5）。
 */
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  ChevronDown,
  FileText,
  HelpCircle,
  MessageSquareText,
  Pencil,
  Trash2,
  Waypoints,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ChunkCard } from "@/components/workspace/knowledge/chunk-card";
import { useI18n } from "@/core/i18n/hooks";
import { listChunksByIds, listDocumentChunks } from "@/core/knowledge/api";
import { useDocuments, useUpdateEvalQuestion } from "@/core/knowledge/hooks";
import type { EvalQuestion, KnowledgeChunk } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { AnchorBlockNotice } from "./anchor-block-notice";
import { toast } from "./kb-toast";
import { useAnchorConfirm } from "./use-anchor-confirm";

/** 改锚编辑区组内分页（spec §2③ D3 细则）：50 片/页，「加载更多」续拉。 */
const EDIT_PAGE_SIZE = 50;

/** 依据按文档分组（2026-09-07）：组头 = 文档标题，组内 = chunk id 中 `#` 后的
    稳定序号——注意不是切片抽屉的位置序号（删除留空洞后位置序会变，这里
    展示稳定身份）。 */
function groupChunksByDoc(
  chunkIds: string[],
): { docId: string; sequences: string[] }[] {
  const groups: { docId: string; sequences: string[] }[] = [];
  for (const chunkId of chunkIds) {
    const [docId, sequence] = chunkId.split("#");
    if (!docId) continue;
    const group = groups.find((entry) => entry.docId === docId);
    if (group) group.sequences.push(sequence ?? "");
    else groups.push({ docId, sequences: [sequence ?? ""] });
  }
  return groups;
}

/** 切片行的单行内容摘要（首行非空文本，CSS 钉单行/两行截断）：编辑勾选区行
    与读态收起摘要共用同口径。 */
function chunkPreview(text: string): string {
  const line = text.split(/\r?\n/).find((entry) => entry.trim().length > 0);
  return (line ?? text).trim();
}

/** chunk id → doc id（`{doc_id}#NNNN`；畸形 id 回退空串）。 */
function docIdOf(chunkId: string): string {
  return chunkId.split("#")[0] ?? "";
}

/** 卡容器（图谱实体抽屉 09-05 定案配方）：bg-card + border + rounded-lg +
    shadow-xs；分组头卡内带 border-b，计数徽章 ml-auto。 */
const CARD = "bg-card text-card-foreground rounded-lg border shadow-xs";
const CARD_HEAD =
  "text-muted-foreground flex items-center gap-1.5 border-b px-3 py-2 text-xs font-medium";

/** 编辑态文档分组的一页切片（组内分页累积；total = 该文档切片总数）。 */
interface DocChunkPage {
  items: KnowledgeChunk[];
  total: number;
  loading: boolean;
}

export interface EvalQuestionDrawerProps {
  question: EvalQuestion | null;
  /** 依据分组的文档标题数据源（与文档 tab 同 queryKey）。 */
  kbId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 删除次按钮：回调给父级（bank）关 drawer 并开确认框。 */
  onDelete: (question: EvalQuestion) => void;
  /** ↗ 复现主按钮：携带 query 跳召回测试面板预填（§7.2）。 */
  onReproduce?: (query: string) => void;
}

export function EvalQuestionDrawer({
  question,
  kbId,
  open,
  onOpenChange,
  onDelete,
  onReproduce,
}: EvalQuestionDrawerProps) {
  const { t } = useI18n();
  const etk = t.knowledge.eval;
  const qtk = etk.questions;
  const aek = qtk.anchorEdit;
  // 文档标题（与文档 tab 同 queryKey，缓存命中不新增请求）；抽屉关时不发请求。
  const docsQuery = useDocuments(open ? kbId : null);
  const docTitle = (docId: string) =>
    (docsQuery.data ?? []).find((doc) => doc.id === docId)?.name ??
    docId.slice(0, 8);
  const groups = question ? groupChunksByDoc(question.relevant_chunk_ids) : [];
  // 落空疑片集（spec §2④）：读时派生 anchor_mismatch 的 chunk_ids。
  const concern = question?.anchor_mismatch ?? null;

  // ── 锚定片正文预览 + 悬空判定（spec §2①/②）：一次 listChunksByIds 两用——
  // 返回集给 ChunkCard 预览，请求集 − 返回集 = 悬空（服务端静默丢缺片）。
  const anchorIds = question?.relevant_chunk_ids ?? [];
  const anchorIdsKey = anchorIds.join("\n");
  const chunksQuery = useQuery({
    queryKey: ["knowledge", "eval-question-anchors", kbId, anchorIdsKey],
    queryFn: () => listChunksByIds(kbId, anchorIds),
    enabled: open && anchorIds.length > 0,
  });
  const chunkById = new Map(
    (chunksQuery.data ?? []).map((chunk) => [chunk.chunk_id, chunk]),
  );
  // 悬空锚集（与读态同一差额口径）。编辑态草稿仍含这些 id，选片区须单列
  // 可摘除行——否则悬空题死锁（草稿带着缺片、missing_chunk 恒拦、无从去掉）。
  const danglingIds = new Set(
    chunksQuery.data !== undefined ? anchorIds.filter((id) => !chunkById.has(id)) : [],
  );

  // ── 改锚编辑态（spec §2③）：草稿勾选集 + 按文档折叠分组的分页缓存。 ──
  const questionId = question?.id ?? null;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [expandedDocs, setExpandedDocs] = useState<Set<string>>(new Set());
  // 读态片级折叠（2026-10-06 甲）：默认全收起，展开集按 chunk id 稳定身份。
  const [openChunks, setOpenChunks] = useState<Set<string>>(new Set());
  const [docPages, setDocPages] = useState<Record<string, DocChunkPage>>({});

  // B′ 拦截状态（keyed=question.id，plan Task 0⑤：key 任意字符串、抽屉按题
  // 隔离）。改锚写口：成功失效题库缓存（bank 行切片数/悬空徽章即时收敛）。
  const anchor = useAnchorConfirm();
  const { blockFor, submit, confirm, clear } = anchor;
  const anchorKey = questionId ?? "";
  const anchorBlock = blockFor(anchorKey);
  const updateMutation = useUpdateEvalQuestion(kbId);

  // 换题即复位编辑态（上一题草稿/红块不残留）。
  useEffect(() => {
    setEditing(false);
    setDraft([]);
    setExpandedDocs(new Set());
    setDocPages({});
  }, [questionId]);

  // B′：勾选锚定集（内容级比较）变化即清红块——下一次保存重新机器核验。
  const draftKey = draft.join("\n");
  useEffect(() => {
    if (editing) clear(anchorKey);
  }, [draftKey, editing, anchorKey, clear]);

  const loadDocPage = useCallback(
    async (docId: string, offset: number) => {
      setDocPages((current) => {
        const prev = current[docId] ?? { items: [], total: 0, loading: false };
        return { ...current, [docId]: { ...prev, loading: true } };
      });
      try {
        const page = await listDocumentChunks(kbId, docId, {
          offset,
          limit: EDIT_PAGE_SIZE,
        });
        setDocPages((current) => {
          const prev = current[docId] ?? { items: [], total: 0, loading: false };
          const seen = new Set(prev.items.map((item) => item.chunk_id));
          const items = [
            ...prev.items,
            ...page.items.filter((item) => !seen.has(item.chunk_id)),
          ];
          return { ...current, [docId]: { items, total: page.total, loading: false } };
        });
      } catch {
        setDocPages((current) => {
          const prev = current[docId] ?? { items: [], total: 0, loading: false };
          return { ...current, [docId]: { ...prev, loading: false } };
        });
      }
    },
    [kbId],
  );

  const enterEdit = () => {
    const anchors = question?.relevant_chunk_ids ?? [];
    setDraft([...anchors]);
    // 含已锚片的文档默认展开，其余默认收起（spec §2③ D3 细则）。
    const initialDocs = new Set(anchors.map(docIdOf).filter(Boolean));
    setExpandedDocs(initialDocs);
    setDocPages({});
    clear(anchorKey);
    setEditing(true);
    for (const docId of initialDocs) void loadDocPage(docId, 0);
  };

  const exitEdit = () => {
    setEditing(false);
    clear(anchorKey);
  };

  const toggleDoc = (docId: string) => {
    setExpandedDocs((current) => {
      const next = new Set(current);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
    // 展开时才拉该文档第一页（未拉过）；已拉过复用缓存。
    if (!expandedDocs.has(docId) && !docPages[docId]) void loadDocPage(docId, 0);
  };

  const toggleDraft = (chunkId: string) => {
    setDraft((current) =>
      current.includes(chunkId)
        ? current.filter((id) => id !== chunkId)
        : [...current, chunkId],
    );
  };

  const toggleChunk = (chunkId: string) => {
    setOpenChunks((current) => {
      const next = new Set(current);
      if (next.has(chunkId)) next.delete(chunkId);
      else next.add(chunkId);
      return next;
    });
  };

  // 提交体共用（原「保存」与红块确认仅 anchor_ack 不同）：复检键物理保证——
  // 原按钮的请求体根本不带 anchor_ack 键（盲双击不可能携带确认标记），
  // 仅红块内「仍要保存」置 true。
  const submitAnchors = (ack: boolean) => {
    if (questionId === null) return Promise.reject(new Error("no question"));
    return updateMutation.mutateAsync({
      questionId,
      body: { relevant_chunk_ids: [...draft], ...(ack ? { anchor_ack: true } : {}) },
    });
  };

  const handleSave = async () => {
    try {
      const saved = await submit(anchorKey, submitAnchors);
      if (!saved) return;
      setEditing(false);
    } catch (error) {
      toast.error(
        error instanceof Error && error.message ? error.message : qtk.saveFailed,
      );
    }
  };

  // 红块内「仍要保存」：anchor_ack=true 覆盖词条级拦截后走正常保存收尾。
  const handleConfirmSave = async () => {
    try {
      const saved = await confirm(anchorKey, submitAnchors);
      if (!saved) return;
      setEditing(false);
    } catch (error) {
      toast.error(
        error instanceof Error && error.message ? error.message : qtk.saveFailed,
      );
    }
  };

  return (
    <Sheet onOpenChange={onOpenChange} open={open}>
      <SheetContent className="w-full overflow-hidden sm:max-w-xl" side="right">
        <div className="flex min-h-0 flex-1 flex-col">
          {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04，EvalRunDrawer 同款）：整抽屉经
              ScrollArea 滚动（type="scroll"、停 2s 淡出），取代原生 overflow-y-auto。 */}
          <ScrollArea
            className="min-h-0 flex-1"
            scrollHideDelay={2000}
            type="scroll"
          >
            {/* sticky 紧凑头（2026-09-08）：query 作标题承载身份（泛称沉 sr-only
                描述）；分类/预期路径芯片行随头——正文不再重复裸徽章行。 */}
            <SheetHeader className="sticky top-0 z-10 border-b bg-background/95 px-4 py-2.5 backdrop-blur-sm">
              <div className="flex min-w-0 items-start gap-1.5 pr-8">
                <HelpCircle className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                <div className="min-w-0">
                  <SheetTitle className="line-clamp-2 text-sm break-words">
                    {question?.query ?? qtk.drawerTitle}
                  </SheetTitle>
                  {question !== null && (
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">
                        {etk.category[question.category]}
                      </Badge>
                      {/* 多路预期（2026-08-28 §3）：与题库表格同口径全量渲染。 */}
                      {question.expected_paths.map((path) => (
                        <Badge key={path} variant="secondary">
                          {path}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <SheetDescription className="sr-only">
                {qtk.drawerTitle}
              </SheetDescription>
            </SheetHeader>
            {question !== null && (
              <div className="flex flex-col gap-3 px-4 py-3">
                <section className={CARD}>
                  <header className={CARD_HEAD}>
                    <MessageSquareText className="size-3.5" />
                    {qtk.answerSection}
                  </header>
                  <div className="p-3">
                    {question.reference_answer ? (
                      <p className="text-sm whitespace-pre-wrap">
                        {question.reference_answer}
                      </p>
                    ) : (
                      <p className="text-muted-foreground text-sm">
                        {qtk.noReferenceAnswer}
                      </p>
                    )}
                  </div>
                </section>

                <section className={CARD}>
                  <header className={CARD_HEAD}>
                    <FileText className="size-3.5" />
                    {qtk.columnRefDocs}
                    <div className="ml-auto flex items-center gap-1.5">
                      {question.relevant_chunk_ids.length > 0 && (
                        <Badge
                          className="px-1.5 text-[10px]"
                          variant="secondary"
                        >
                          {qtk.drawerChunksCount(question.relevant_chunk_ids.length)}
                        </Badge>
                      )}
                      {/* 改锚入口（2026-10-06）：⇄ 读态/编辑态切换。 */}
                      <Button
                        className="h-6 px-2 text-[10px]"
                        onClick={editing ? exitEdit : enterEdit}
                        size="sm"
                        variant="outline"
                      >
                        <Pencil className="mr-1 size-3" />
                        {aek.button}
                      </Button>
                    </div>
                  </header>
                  {editing ? (
                    /* 改锚编辑区（spec §2③）：按文档折叠分组勾选——组头「已选
                       n/N」实时、含已锚片文档默认展开、组内 50/页加载更多、
                       勾后可整组收起；清空勾选 = 解除锚定（允许）。 */
                    <div className="flex flex-col gap-2.5 p-3">
                      {(docsQuery.data ?? []).map((doc) => {
                        const page = docPages[doc.id] ?? {
                          items: [],
                          total: 0,
                          loading: false,
                        };
                        // 组头分母：已拉过分页用权威 total，未拉过显文档行的
                        // chunk_count（0 = 空文档，不是「未加载」）。
                        const total =
                          docPages[doc.id] !== undefined
                            ? page.total
                            : (doc.chunk_count ?? 0);
                        const selectedCount = draft.filter((id) =>
                          id.startsWith(`${doc.id}#`),
                        ).length;
                        const expanded = expandedDocs.has(doc.id);
                        return (
                          <div
                            className="flex min-w-0 flex-col gap-1 rounded-md border px-2 py-1.5"
                            key={doc.id}
                          >
                            <button
                              aria-expanded={expanded}
                              className="flex w-full items-center gap-1.5 text-left text-xs font-medium"
                              onClick={() => toggleDoc(doc.id)}
                              type="button"
                            >
                              <ChevronDown
                                className={cn(
                                  "size-3 shrink-0 transition-transform",
                                  expanded && "rotate-180",
                                )}
                              />
                              <span className="truncate">{doc.name}</span>
                              <span className="text-muted-foreground ml-auto shrink-0 tabular-nums">
                                {aek.selected(selectedCount, total)}
                              </span>
                            </button>
                            {expanded && (
                              <div className="flex flex-col gap-1 pl-5">
                                {page.items.map((chunk) => (
                                  <label
                                    className="flex cursor-pointer items-start gap-2 py-0.5"
                                    key={chunk.chunk_id}
                                  >
                                    <Checkbox
                                      checked={draft.includes(chunk.chunk_id)}
                                      onCheckedChange={() =>
                                        toggleDraft(chunk.chunk_id)
                                      }
                                    />
                                    <span className="line-clamp-2 min-w-0 flex-1 text-xs">
                                      {chunkPreview(chunk.text)}
                                    </span>
                                  </label>
                                ))}
                                {/* 悬空锚草稿行（读态警示行的可摘除版）。 */}
                                {draft
                                  .filter(
                                    (id) =>
                                      id.startsWith(`${doc.id}#`) && danglingIds.has(id),
                                  )
                                  .map((id) => (
                                    <label
                                      className="flex cursor-pointer items-start gap-2 py-0.5"
                                      key={id}
                                    >
                                      <Checkbox
                                        checked
                                        onCheckedChange={() => toggleDraft(id)}
                                      />
                                      <span className="flex items-center gap-1.5 text-xs">
                                        <Badge
                                          className="font-mono text-[10px]"
                                          variant="destructive"
                                        >
                                          #{id.split("#")[1]}
                                        </Badge>
                                        <span className="text-destructive">
                                          {qtk.danglingBadge}
                                        </span>
                                      </span>
                                    </label>
                                  ))}
                                {page.items.length < page.total && (
                                  <Button
                                    disabled={page.loading}
                                    onClick={() =>
                                      void loadDocPage(doc.id, page.items.length)
                                    }
                                    size="sm"
                                    variant="outline"
                                  >
                                    {aek.loadMore}
                                  </Button>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                      <div className="flex items-center gap-2">
                        <Button
                          disabled={updateMutation.isPending}
                          onClick={() => void handleSave()}
                          size="sm"
                        >
                          {aek.save}
                        </Button>
                        <Button
                          disabled={updateMutation.isPending}
                          onClick={exitEdit}
                          size="sm"
                          variant="outline"
                        >
                          {aek.cancel}
                        </Button>
                      </div>
                      {/* B′ 红块：保存按钮行正下方；原「保存」保留原语义（永不带
                          anchor_ack），仅红块内「仍要保存」携 anchor_ack=true。 */}
                      {anchorBlock !== null && (
                        <AnchorBlockNotice
                          confirmLabel={etk.anchorBlock.confirmUpdate}
                          confirming={updateMutation.isPending}
                          detail={anchorBlock}
                          onConfirm={() => void handleConfirmSave()}
                        />
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-col gap-2.5 p-3">
                      {groups.length > 0 ? (
                        groups.map((group) => {
                          const title = docTitle(group.docId);
                          return (
                            <div
                              className="flex min-w-0 flex-col gap-1.5"
                              key={group.docId}
                            >
                              {/* 组头悬浮统一（2026-10-06）：原生 title 换项目
                                  Tooltip（Radix 主题样式，与文档名 tooltip 同款）。 */}
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="min-w-0 truncate text-xs font-medium">
                                    {title}
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent className="max-w-60 text-pretty">
                                  {title}
                                </TooltipContent>
                              </Tooltip>
                              {group.sequences.map((sequence) => {
                                const chunkId = `${group.docId}#${sequence}`;
                                const chunk = chunkById.get(chunkId);
                                // 悬空判定（spec §2①）：取数返回后请求集 − 返回集。
                                const dangling =
                                  chunksQuery.data !== undefined &&
                                  chunk === undefined;
                                if (dangling) {
                                  return (
                                    <div
                                      className="text-destructive flex items-center gap-1.5 text-xs"
                                      key={chunkId}
                                    >
                                      <Badge
                                        className="font-mono text-[10px]"
                                        variant="destructive"
                                      >
                                        #{sequence}
                                      </Badge>
                                      <span>{qtk.danglingBadge}</span>
                                    </div>
                                  );
                                }
                                const open = openChunks.has(chunkId);
                                const suspect =
                                  concern?.chunk_ids.includes(chunkId) ?? false;
                                const triggerRow = (
                                  <button
                                    aria-expanded={open}
                                    className="flex w-full flex-col items-start gap-0.5 text-left"
                                    onClick={() => toggleChunk(chunkId)}
                                    type="button"
                                  >
                                    <span className="flex items-center gap-1.5">
                                      <ChevronDown
                                        className={cn(
                                          "size-3 shrink-0 transition-transform",
                                          open && "rotate-180",
                                        )}
                                      />
                                      {/* 稳定序号徽章保留（chunk id 身份）。 */}
                                      <Badge
                                        className="font-mono text-[10px]"
                                        variant="secondary"
                                      >
                                        #{sequence}
                                      </Badge>
                                      {/* 疑片「存疑」徽章（spec §2④，B1=甲）：
                                          随触发行可见（收起态不藏进展开区），
                                          amber 档＝可确认待人看。 */}
                                      {suspect && (
                                        <Badge
                                          className="border-amber-500/40 px-1.5 text-[10px] text-amber-700 dark:text-amber-500"
                                          variant="outline"
                                        >
                                          {qtk.mismatchBadge}
                                        </Badge>
                                      )}
                                    </span>
                                    {!open && chunk !== undefined && (
                                      <span className="text-muted-foreground line-clamp-2 pl-[18px] text-xs">
                                        {chunkPreview(chunk.text)}
                                      </span>
                                    )}
                                  </button>
                                );
                                return (
                                  <div
                                    className="flex min-w-0 flex-col gap-1"
                                    key={chunkId}
                                  >
                                    {/* 片级折叠触发行（2026-10-06 甲）：默认全
                                        收起——这面用途是扫锚了哪几片；摘要行与
                                        编辑勾选区同口径（chunkPreview）。悬空行
                                        无内容可折，保持单列警示。疑片行悬浮＝
                                        项目 Tooltip 机器依据（红块同款文案）。 */}
                                    {suspect && concern !== null ? (
                                      <Tooltip>
                                        <TooltipTrigger asChild>
                                          {triggerRow}
                                        </TooltipTrigger>
                                        <TooltipContent className="max-w-60">
                                          <AnchorBlockNotice detail={concern} />
                                        </TooltipContent>
                                      </Tooltip>
                                    ) : (
                                      triggerRow
                                    )}
                                    {open && chunk !== undefined && (
                                      <ChunkCard
                                        docId={chunk.doc_id}
                                        entities={chunk.entities}
                                        headingPath={chunk.heading_path}
                                        kbId={kbId}
                                        page={chunk.page}
                                        text={chunk.text}
                                        tokenCount={chunk.token_count}
                                      />
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          );
                        })
                      ) : (
                        <p className="text-muted-foreground text-sm">
                          {qtk.unanchored}
                        </p>
                      )}
                    </div>
                  )}
                </section>

                {/* 实体卡（2026-09-08）：仅有值显——空标注诚实缺省不摆空卡；
                    Waypoints 与召回面板图谱路 PATH_ICONS 同源词汇。 */}
                {question.relevant_entities.length > 0 && (
                  <section className={CARD}>
                    <header className={CARD_HEAD}>
                      <Waypoints className="size-3.5" />
                      {qtk.entitiesSection}
                      <Badge
                        className="ml-auto px-1.5 text-[10px]"
                        variant="secondary"
                      >
                        {question.relevant_entities.length}
                      </Badge>
                    </header>
                    <div className="flex flex-wrap gap-1 p-3">
                      {question.relevant_entities.map((entity) => (
                        <Badge key={entity} variant="outline">
                          {entity}
                        </Badge>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}
          </ScrollArea>
          {/* 动作栏（2026-09-08）：ScrollArea 外钉底——短内容不悬空、长内容
              不随滚；复现主/删除次语义不变（删除回调父级开确认框）。 */}
          {question !== null && (
            <div className="flex shrink-0 items-center gap-2 border-t px-4 py-2.5">
              <Button onClick={() => onReproduce?.(question.query)} size="sm">
                <ArrowUpRight className="size-4" />
                {qtk.rowReproduce}
              </Button>
              <Button
                onClick={() => onDelete(question)}
                size="sm"
                variant="outline"
              >
                <Trash2 className="text-destructive size-4" />
                {qtk.rowDelete}
              </Button>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
