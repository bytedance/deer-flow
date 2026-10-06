"use client";

import {
  BookOpen,
  ChartScatter,
  FlaskConical,
  Search,
  Timer,
  Waypoints,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import { useCardDrawers } from "@/core/knowledge/card-drawers";
import { stripSummaryHeading, textLead } from "@/core/knowledge/format";
import { useRecallTest } from "@/core/knowledge/hooks";
import type {
  RecallGraphEvidence,
  RecallPathName,
  RecallTestResponse,
  RecallVectorHit,
  RecallWikiHit,
  VectorRetrievalOverlay,
} from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { EvalSaveQuestionDialog } from "./eval-save-question-dialog";
import { toast } from "./kb-toast";
import { RecallGraphMini } from "./recall-graph-mini";

function formatScore(score: number | null): string {
  return score === null ? "—" : score.toFixed(3);
}

const PATH_ORDER: RecallPathName[] = ["vector", "graph", "wiki"];
/** 耗时排名色（2026-09-05 定案）：固定三色按跨路排名取色——
    最快=绿、中间=橙绿(lime)、最慢=橙；淡底配方同 workspace-change-badge
    （bg-x-500/10 + dark 提亮文字）。 */
const ELAPSED_RANK_CLASSES = [
  "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  "bg-lime-500/10 text-lime-700 dark:text-lime-300",
  "bg-orange-500/10 text-orange-700 dark:text-orange-300",
] as const;
/** 路图标（2026-09-05 两层重设计）：散点=向量空间、节点图=图谱路、
    BookOpen=百科（与百科抽屉/词条区同源词汇）。 */
const PATH_ICONS: Record<RecallPathName, typeof BookOpen> = {
  vector: ChartScatter,
  graph: Waypoints,
  wiki: BookOpen,
};

/** 单行命中行（三路统一解剖，2026-09-05 两层重设计）：复选框 + #rank +
    标题/文档名(≤45%) + 首行摘要(flex-1 truncate 淡化) + 页码 + 分数。
    行点击统一开右抽（切片行→切片总览抽屉定位该切片），内联展开退役；
    checked/onCheckChange 挂「存为考题」勾选（spec §7.1）。 */
function ChunkHitRow({
  hit,
  score,
  testId,
  checked,
  onCheckChange,
  selectLabel,
  selectTestId,
  anySelected,
  sliceLabel,
  onOpen,
}: {
  hit: {
    chunk_id: string;
    doc_name: string;
    text: string;
    heading_path: string[];
    page: number | null;
    rank?: number;
  };
  score: number | null;
  testId: string;
  checked: boolean;
  onCheckChange: () => void;
  /** 勾选框 aria-label（调用点用 i18n 组装——模块级组件拿不到 tr）。 */
  selectLabel: string;
  /** 勾选框 testid：带路径前缀——同一 chunk 可能同时命中两路。 */
  selectTestId: string;
  /** 已有勾选时全量显现复选框（百科 Tab 同款配方）。 */
  anySelected: boolean;
  /** 切片文档内序号悬浮气泡文案（调用点 i18n 组装「切片 #K」，与抽屉徽章
      同词汇）；缺 chunk_position 时 undefined → 无气泡、行内不挂数字。 */
  sliceLabel?: string;
  onOpen: () => void;
}) {
  const rowButton = (
    <button
      className="hover:bg-muted/50 flex min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-1.5 text-left"
      data-testid={testId}
      type="button"
      onClick={onOpen}
    >
      {hit.rank != null && (
        <span className="text-muted-foreground shrink-0 text-xs">
          #{hit.rank}
        </span>
      )}
      <span className="max-w-[45%] shrink-0 truncate text-sm font-medium">
        {hit.doc_name}
      </span>
      {/* 预览 = 正文首非空行（2026-09-05 回退定案）：标题/标题链做预览会因
          标题过短留大片空白；正文首行够长填满行宽，且同文档不同切片
          正文天然不同。切片序号改悬浮气泡展示（行内数字看着奇怪）。 */}
      <span className="text-muted-foreground/70 min-w-0 flex-1 truncate text-xs">
        {textLead(hit.text, 1)}
      </span>
      {hit.page != null && (
        <span className="text-muted-foreground shrink-0 text-xs">
          p.{hit.page}
        </span>
      )}
      <span className="text-muted-foreground ml-auto shrink-0 font-mono text-xs">
        {formatScore(score)}
      </span>
    </button>
  );
  return (
    <div
      className="group flex items-center gap-1.5"
      onContextMenu={(event) => {
        // 右键 = 选中/取消选中（2026-09-05）：容器内容右键此前无动作。
        event.preventDefault();
        onCheckChange();
      }}
    >
      <Checkbox
        aria-label={selectLabel}
        checked={checked}
        className={cn(
          "shrink-0 opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100",
          anySelected && "opacity-100",
        )}
        data-testid={selectTestId}
        onCheckedChange={onCheckChange}
      />
      {sliceLabel != null ? (
        <Tooltip content={sliceLabel}>{rowButton}</Tooltip>
      ) : (
        rowButton
      )}
    </div>
  );
}

/**
 * P1 检索测试 tab (phase-2 batch-1, spec §3): fan one query out to the three
 * retrieval paths and compare hits/scores/elapsed side by side. 三路并列
 * （2026-09-05）：各占 1/3 高容器、容器内 ScrollArea 内滚（解挤占保同屏）；
 * 切片行点击开切片总览抽屉定位该切片，wiki 行开条目/卡片抽屉（overlay —
 * never switches the middle tab）。Keep-alive: the pane stays mounted.
 */
export function RecallTestPanel({
  kbId,
  onOpenWikiEntry,
  onOpenManualCard,
  onOpenChunkHit,
  onViewInVectorSpace,
  prefillQuery,
  onPrefillConsumed,
}: {
  kbId: string;
  onOpenWikiEntry: (entryId: string) => void;
  /** Phase-3 P6（spec §8 混排）：manual 命中开卡片抽屉 —— 卡片 id 走 wiki 详情接口必然 404。 */
  onOpenManualCard?: (cardId: string) => void;
  /** 切片命中行点击（2026-09-05 两层重设计）：开切片总览抽屉并定位该切片。 */
  onOpenChunkHit?: (chunkId: string) => void;
  /**
   * P6 检索联动（2026-08-15 spec §9 通道一）：工具栏「在向量空间查看」图标按钮——
   * page 层切 tab 并完成叠加（query 落点 + vector 路命中高亮）。
   * 2026-09-05：从结果区独占一行收进搜索框同行右侧（仅图标 + tooltip），
   * 无结果时不渲染、vector 路零命中时禁用。
   */
  onViewInVectorSpace?: (overlay: VectorRetrievalOverlay) => void;
  /** 复现通道（§7.2）：评测侧跳转携带的预填 query；消费后回调清空。 */
  prefillQuery?: string | null;
  onPrefillConsumed?: () => void;
}) {
  const { t } = useI18n();
  const tr = t.knowledge.recallTest;
  const recallTest = useRecallTest(kbId);
  // 人工卡片归属抽屉（2026-09-05）：与我的条目行图标/详情抽屉头部同源——
  // 命中行芯片展示抽屉名称而非泛称「我的卡片」。
  const { drawers, membership } = useCardDrawers(kbId);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const result: RecallTestResponse | null = recallTest.data ?? null;

  // 复现预填通道（§7.2）：写入输入框即消费——只预填，不替用户发起检索。
  useEffect(() => {
    if (prefillQuery) {
      setQuery(prefillQuery);
      onPrefillConsumed?.();
    }
  }, [prefillQuery, onPrefillConsumed]);

  // 「存为考题」勾选（§7.1）：vector 命中 + graph 证据按 chunk id 去重，
  // 百科词条行（2026-08-28 §5）按其源切片整体进/出锚定集；记录来源路径供
  // dialog 默认预期路径（多路化：混路即多勾）。
  const [selectedChunks, setSelectedChunks] = useState<
    { id: string; path: RecallPathName }[]
  >([]);
  // 人工卡片勾选（2026-09-05）：卡片无源切片，勾选只贡献「来源路径=wiki」
  // 与计数，提交体锚定为空——走题库既有无锚定降级语义（仅参与路径判定）。
  const [selectedCards, setSelectedCards] = useState<string[]>([]);
  const [saveOpen, setSaveOpen] = useState(false);
  // 路容器收起态（2026-09-05，百科 Tab 同款）：标题栏点击折叠，收起路只留
  // 单行头（shrink-0），其余路 flex-1 吸收释放高度顶上来。
  const [collapsedPaths, setCollapsedPaths] = useState<
    Record<RecallPathName, boolean>
  >({ vector: false, graph: false, wiki: false });
  // 图谱路容器视图（2026-09-05）：证据行 ↔ 实体/关系段控切换——实体/关系
  // 多时会吃掉整个 1/3 容器，切换后各视图独占容器高度互不挤占；默认证据。
  const [graphView, setGraphView] = useState<"evidence" | "entities">(
    "evidence",
  );
  const toggleChunk = (chunkId: string, path: "vector" | "graph") =>
    setSelectedChunks((current) =>
      current.some((item) => item.id === chunkId)
        ? current.filter((item) => item.id !== chunkId)
        : [...current, { id: chunkId, path }],
    );
  const wikiEntryChecked = (hit: RecallWikiHit) => {
    const sourceIds = hit.source_chunk_ids ?? [];
    if (sourceIds.length === 0) return false;
    const selected = new Set(selectedChunks.map((item) => item.id));
    return sourceIds.every((id) => selected.has(id));
  };
  // 词条行勾选 = 源切片整体进锚定集（已选的切片不重复加，保提交体无重）。
  const toggleWikiEntry = (hit: RecallWikiHit) => {
    const sourceIds = hit.source_chunk_ids ?? [];
    if (sourceIds.length === 0) return;
    setSelectedChunks((current) => {
      const selected = new Set(current.map((item) => item.id));
      if (sourceIds.every((id) => selected.has(id))) {
        return current.filter((item) => !sourceIds.includes(item.id));
      }
      const additions = sourceIds
        .filter((id) => !selected.has(id))
        .map((id) => ({ id, path: "wiki" as const }));
      return [...current, ...additions];
    });
  };
  const toggleManualCard = (cardId: string) =>
    setSelectedCards((current) =>
      current.includes(cardId)
        ? current.filter((id) => id !== cardId)
        : [...current, cardId],
    );
  // 勾选总量（2026-09-05）：悬浮栏显隐/复选框全量显现/dialog 计数共用。
  const selectionCount = selectedChunks.length + selectedCards.length;
  const anySelected = selectionCount > 0;
  const selectionPaths = new Set(selectedChunks.map((item) => item.path));
  if (selectedCards.length > 0) selectionPaths.add("wiki");
  // 默认勾选 = 来源路径集合（2026-08-28 多路化）：混路即多勾，不再降级单路；
  // Set 迭代序 = 勾选序，与提交顺序一致。空选时按钮不展示，回退保 prop 非空。
  const defaultSavePaths: RecallPathName[] =
    selectionPaths.size > 0 ? [...selectionPaths] : ["vector"];

  const run = () => {
    const trimmed = query.trim();
    if (!trimmed || recallTest.isPending) {
      return;
    }
    setSelectedChunks([]);
    setSelectedCards([]);
    const clampedTopK = Math.min(20, Math.max(1, Math.trunc(topK) || 5));
    recallTest.mutate(
      { query: trimmed, top_k: clampedTopK },
      {
        onError: (error) => {
          toast.error(
            error instanceof Error && error.message ? error.message : tr.failed,
          );
        },
      },
    );
  };

  const pathName: Record<RecallPathName, string> = {
    vector: tr.vectorPath,
    graph: tr.graphPath,
    wiki: tr.wikiPath,
  };
  // 总览卡统计量（2026-09-05）：命中数/耗时/score 类型——跨路只比这些，
  // 分数语义各路不同不可互比（types 契约注释）。
  const pathCounts: Record<RecallPathName, number> = result
    ? {
        vector: result.paths.vector.hits.length,
        graph: result.paths.graph.evidence.length,
        wiki: result.paths.wiki.hits.length,
      }
    : { vector: 0, graph: 0, wiki: 0 };
  const pathMessage: Record<RecallPathName, string> = result
    ? {
        vector: result.paths.vector.message,
        graph: result.paths.graph.message,
        wiki: result.paths.wiki.message,
      }
    : { vector: "", graph: "", wiki: "" };
  // 排名 = 去重排序耗时值的下标（2026-09-05）：同值共享较快档色，
  // 不对持平局产生误导色；下标即 ELAPSED_RANK_CLASSES 档位。
  const sortedElapsed = result
    ? [...new Set(PATH_ORDER.map((path) => result.elapsed_ms[path]))].sort(
        (a, b) => a - b,
      )
    : [];
  const elapsedRankClass = (path: RecallPathName) =>
    ELAPSED_RANK_CLASSES[sortedElapsed.indexOf(result?.elapsed_ms[path] ?? 0)] ??
    "bg-muted/60 text-muted-foreground";

  // 三路并列（2026-09-05）：行清单按路提纯，三个 1/3 高容器各渲染各的、
  // 容器内 ScrollArea 内滚（百科 Tab 容器同款配方）；图谱实体/关系由实体
  // 视图的关系图承接（recall-graph-mini，徽章墙退役）。
  const vectorRows = result?.paths.vector.hits.map((hit: RecallVectorHit) => (
    <ChunkHitRow
      anySelected={anySelected}
      checked={selectedChunks.some((item) => item.id === hit.chunk_id)}
      hit={hit}
      key={hit.chunk_id}
      score={hit.score}
      testId={`recall-vector-hit-${hit.chunk_id}`}
      onCheckChange={() => toggleChunk(hit.chunk_id, "vector")}
      onOpen={() => onOpenChunkHit?.(hit.chunk_id)}
      selectLabel={`${tr.saveAsQuestion.button}: ${hit.doc_name}`}
      selectTestId={`recall-select-vector-${hit.chunk_id}`}
      sliceLabel={
        hit.chunk_position != null
          ? tr.slicePosition(hit.chunk_position)
          : undefined
      }
    />
  ));
  const graphRows = result?.paths.graph.evidence.map(
    (hit: RecallGraphEvidence, index: number) => (
      <ChunkHitRow
        anySelected={anySelected}
        checked={selectedChunks.some((item) => item.id === hit.chunk_id)}
        // 证据序排名（2026-09-05）：select_evidence 产出序 = 图谱消息引用编号序，
        // 前端按列表位置赋 rank，三路行解剖统一。
        hit={{ ...hit, rank: index + 1 }}
        key={hit.chunk_id}
        score={hit.score}
        testId={`recall-graph-hit-${hit.chunk_id}`}
        onCheckChange={() => toggleChunk(hit.chunk_id, "graph")}
        onOpen={() => onOpenChunkHit?.(hit.chunk_id)}
        selectLabel={`${tr.saveAsQuestion.button}: ${hit.doc_name}`}
        selectTestId={`recall-select-graph-${hit.chunk_id}`}
        sliceLabel={
          hit.chunk_position != null
            ? tr.slicePosition(hit.chunk_position)
            : undefined
        }
      />
    ),
  );
  const wikiRows = result?.paths.wiki.hits.map((hit: RecallWikiHit) => {
    // 勾选三态（2026-09-05）：人工卡片无源切片——勾选仅记录预期路径（wiki）、
    // 不产生锚定（无锚定题降级语义）；词条行仍按源切片整体进/出锚定集；
    // 无源切片的词条禁用勾选。
    const isManual = hit.source_type === "manual";
    const entryAnchorable = (hit.source_chunk_ids?.length ?? 0) > 0;
    // 归属抽屉（2026-09-05）：membership 卡→抽屉；未归档/归属已删为 undefined。
    const ownerDrawer = isManual
      ? drawers.find((drawer) => drawer.id === membership[hit.entry_id])
      : undefined;
    return (
      <div
        className="group flex items-center gap-1.5"
        key={hit.entry_id}
        onContextMenu={(event) => {
          // 右键 = 选中/取消选中（2026-09-05）；无源切片词条不可锚定→不切换。
          event.preventDefault();
          if (isManual) toggleManualCard(hit.entry_id);
          else if (entryAnchorable) toggleWikiEntry(hit);
        }}
      >
        <Checkbox
          aria-label={`${tr.saveAsQuestion.button}: ${hit.title}`}
          checked={
            isManual
              ? selectedCards.includes(hit.entry_id)
              : wikiEntryChecked(hit)
          }
          className={cn(
            "shrink-0 opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100",
            anySelected && "opacity-100",
          )}
          data-testid={`recall-select-wiki-${hit.entry_id}`}
          disabled={!isManual && !entryAnchorable}
          onCheckedChange={() =>
            isManual
              ? toggleManualCard(hit.entry_id)
              : toggleWikiEntry(hit)
          }
        />
        <button
          className="hover:bg-muted/50 flex min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-1.5 text-left"
          data-testid={`recall-wiki-hit-${hit.entry_id}`}
          title={isManual ? tr.wikiAnchorTooltip : undefined}
          type="button"
          onClick={() =>
            isManual
              ? onOpenManualCard?.(hit.entry_id)
              : onOpenWikiEntry(hit.entry_id)
          }
        >
          <span className="text-muted-foreground shrink-0 text-xs">
            #{hit.rank}
          </span>
          <span className="max-w-[45%] shrink-0 truncate text-sm font-medium">
            {hit.title}
          </span>
          {/* 人工卡片归属芯片（2026-09-05）：展示所属抽屉名称且置于条目名称之后
              （此前为名称前的泛称「我的卡片」）；未归档/归属已删回退泛称。 */}
          {isManual && (
            <Badge className="shrink-0 text-[10px]" variant="secondary">
              {ownerDrawer?.name ?? t.knowledge.chat.sourceTypeManual}
            </Badge>
          )}
          {/* 摘要剥掉后端 content[:120] 里的「# 标题」H1；标题实/摘要淡、溢出统一 truncate（对齐百科 Tab 单行样式） */}
          <span className="text-muted-foreground/70 min-w-0 flex-1 truncate text-xs">
            {stripSummaryHeading(hit.summary)}
          </span>
          <span className="text-muted-foreground ml-auto shrink-0 font-mono text-xs">
            {formatScore(hit.score)}
          </span>
        </button>
      </div>
    );
  });

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      data-testid="recall-test-panel"
    >
      {/* Controls：成本提示不再独占一行（2026-08-30），收进「开始检索」按钮 tooltip；
          py-2 + 栏内控件全锁 h-7 → 44px，对齐全知识库页工具栏基准（默认 h-9 会撑成 52px）；
          搜索框补左侧 Search 图标（2026-09-05，全知识库搜索框同款配方 pl-7）；
          「在向量空间查看」收为同行右侧图标按钮（不再独占一行）。
          去 border-b（2026-09-05）：下方三路已是各自带边框/头部的 bg-card 容器，
          分隔交给留白 + 卡片边框，工具栏横线冗余（与 vector/document tab 去线同理，
          避免与卡片顶边双线夹击）。 */}
      <div className="flex items-center gap-2 px-4 py-2">
        <div className="relative min-w-0 flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <Input
            className="h-7 pr-2 pl-7 text-xs"
            placeholder={tr.queryPlaceholder}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                run();
              }
            }}
          />
        </div>
        <Input
          aria-label={tr.topK}
          className="h-7 w-20 shrink-0 text-xs"
          max={20}
          min={1}
          type="number"
          value={topK}
          onChange={(event) => setTopK(Number(event.target.value))}
        />
        <Tooltip content={tr.costHint}>
          <Button
            className="h-7 shrink-0"
            disabled={!query.trim() || recallTest.isPending}
            onClick={run}
          >
            {recallTest.isPending ? tr.running : tr.run}
          </Button>
        </Tooltip>
        {result && onViewInVectorSpace && (
          <Tooltip content={tr.viewInVectorSpace}>
            <Button
              aria-label={tr.viewInVectorSpace}
              className="h-7 w-7 shrink-0"
              disabled={result.paths.vector.hits.length === 0}
              size="icon"
              variant="ghost"
              onClick={() =>
                onViewInVectorSpace({
                  source: "recall",
                  text: result.query,
                  hits: result.paths.vector.hits.map((hit) => ({
                    pointId: hit.chunk_id,
                    score: hit.score,
                  })),
                })
              }
            >
              <ChartScatter className="size-3.5" />
            </Button>
          </Tooltip>
        )}
      </div>

      {/* Results（2026-09-05 三路并列）：外层不再整滚——三路各占 1/3 高并列，
          每容器内 ScrollArea 内滚（百科 Tab 容器同款配方：type="scroll"、
          停 2s 淡出）；解挤占同时保跨路同屏可见；行去外边框（容器已包裹，
          百科 Tab 行同款）；存为考题栏悬浮于结果区底部（不占流、不抖动）。 */}
      <div className="relative flex min-h-0 flex-1 flex-col gap-2 px-4 py-3">
        {!result && (
          // absolute inset-0（2026-09-04 修居中回归）：空态锚定本 relative 容器水平+垂直居中。
          <div className="text-muted-foreground absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm">
            <FlaskConical className="size-5" />
            <p>{tr.empty}</p>
          </div>
        )}
        {result && (
          <>
            {/* D4 失配提示（spec 2026-10-04 §2.4）：库的向量空间与当前配置不一致
                ⇒ 复用设置页同一条文案（embeddingChangeWarning）——查询不被拒绝，
                只提示检索质量会降；缺键/一致/未盖章都不显示。 */}
            {result.embedding_mismatch && (
              <p className="text-destructive text-xs" role="alert">
                {t.settings.functionalModels.embeddingChangeWarning}
              </p>
            )}
            <div className="flex min-h-0 flex-1 flex-col gap-2">
              {PATH_ORDER.map((path) => {
                const Icon = PATH_ICONS[path];
                const isCollapsed = collapsedPaths[path];
                return (
                  <section
                    className={cn(
                      "bg-card text-card-foreground flex flex-col rounded-lg border shadow-xs",
                      isCollapsed ? "shrink-0" : "min-h-0 flex-1",
                    )}
                    data-testid={`recall-path-${path}`}
                    key={path}
                  >
                    {/* 容器标题栏（2026-09-05）：左簇为收起 toggle 按钮（chevron
                        退役——整栏点击即收起，箭头视觉噪声）；图谱路右挂视图
                        切换段控（证据 ↔ 实体/关系），与 toggle 兄弟节点避免
                        按钮嵌套。 */}
                    <div
                      className={cn(
                        "flex items-center gap-2 px-3 py-2",
                        !isCollapsed && "border-b",
                      )}
                    >
                      <button
                        aria-expanded={!isCollapsed}
                        className="hover:bg-muted/50 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md px-2 py-0.5 text-left transition-colors"
                        data-testid={`recall-path-toggle-${path}`}
                        type="button"
                        onClick={() =>
                          setCollapsedPaths((current) => ({
                            ...current,
                            [path]: !current[path],
                          }))
                        }
                      >
                        <Icon className="text-muted-foreground size-4 shrink-0" />
                        <span className="text-sm font-medium">
                          {pathName[path]}
                        </span>
                        <Badge className="shrink-0 text-[10px]" variant="outline">
                          {result.score_type[path]}
                        </Badge>
                      </button>
                      {/* 2026-09-05：视图切换段控置于左侧胶囊后（用户定位置），
                          与 toggle 兄弟节点避免按钮嵌套。 */}
                      {path === "graph" && (
                        <span className="bg-muted/60 flex shrink-0 items-center rounded-md p-0.5">
                          <button
                            aria-pressed={graphView === "evidence"}
                            className={cn(
                              "rounded px-1.5 py-0.5 text-[10px] transition-colors",
                              graphView === "evidence"
                                ? "bg-card text-foreground shadow-xs"
                                : "text-muted-foreground hover:text-foreground",
                            )}
                            data-testid="recall-graph-view-evidence"
                            type="button"
                            onClick={() => setGraphView("evidence")}
                          >
                            {tr.evidenceView(result.paths.graph.evidence.length)}
                          </button>
                          <button
                            aria-pressed={graphView === "entities"}
                            className={cn(
                              "rounded px-1.5 py-0.5 text-[10px] transition-colors",
                              graphView === "entities"
                                ? "bg-card text-foreground shadow-xs"
                                : "text-muted-foreground hover:text-foreground",
                            )}
                            data-testid="recall-graph-view-entities"
                            disabled={
                              result.paths.graph.entities.length +
                                result.paths.graph.relations.length ===
                              0
                            }
                            type="button"
                            onClick={() => setGraphView("entities")}
                          >
                            {tr.entitiesView(result.paths.graph.entities.length)}
                          </button>
                        </span>
                      )}
                      {/* 2026-09-05：耗时/计数右移——左侧只留「哪路 + 分数语义」，
                          对比量集中右侧便于一列扫读；耗时芯片按跨路排名取固定
                          三色（绿/橙绿/橙），一眼分辨最快最慢。 */}
                      <span className="ml-auto flex shrink-0 items-center gap-1.5">
                        <span
                          className={cn(
                            "flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10px] tabular-nums",
                            elapsedRankClass(path),
                          )}
                          data-testid={`recall-elapsed-${path}`}
                        >
                          <Timer className="size-3" />
                          {result.elapsed_ms[path]} ms
                        </span>
                        <Badge
                          className="shrink-0 text-[10px] tabular-nums"
                          variant="secondary"
                        >
                          {pathCounts[path]}
                        </Badge>
                      </span>
                      {/* 2026-09-05：标题下文字介绍退役——计数芯片已足，message
                          仅留零命中/失败路的容器内居中反馈，把高度还给内容。 */}
                    </div>
                    {!isCollapsed &&
                      (path === "graph" && graphView === "entities" ? (
                        // 实体视图：关系图独占容器（不进 ScrollArea——图自漫游缩放）
                        <div className="min-h-0 flex-1">
                          <RecallGraphMini
                            entities={result.paths.graph.entities}
                            relations={result.paths.graph.relations}
                          />
                        </div>
                      ) : (
                        <ScrollArea
                          className="min-h-0 flex-1"
                          scrollHideDelay={2000}
                          type="scroll"
                        >
                          <div className="flex flex-col gap-1.5 p-2">
                            {pathCounts[path] === 0 ? (
                              // 零命中/失败路：message 容器内居中（同空态配方节奏）
                              <p className="text-muted-foreground py-6 text-center text-xs">
                                {pathMessage[path]}
                              </p>
                            ) : (
                              <>
                                {path === "graph" && graphRows}
                                {path === "vector" && vectorRows}
                                {path === "wiki" && wikiRows}
                              </>
                            )}
                          </div>
                        </ScrollArea>
                      ))}
                  </section>
                );
              })}
            </div>

            {/* 存为考题栏（§7.1，2026-09-05 改悬浮）：勾选 ≥1 浮出——absolute 悬浮
                于结果区底部居中，不参与三路 flex 布局（旧在流 shrink-0 栏浮出时
                压缩三容器高度产生抖动）；造题主入口，题库随使用自然生长。 */}
            {anySelected && (
              <div className="pointer-events-none absolute inset-x-0 bottom-3 z-10 flex justify-center">
                <div className="bg-card/95 text-card-foreground pointer-events-auto flex items-center gap-3 rounded-full border px-4 py-1.5 shadow-lg backdrop-blur-sm">
                  <span className="text-muted-foreground text-xs">
                    {tr.saveAsQuestion.selectedCount(selectionCount)}
                  </span>
                  <Button size="sm" onClick={() => setSaveOpen(true)}>
                    <FlaskConical className="size-3.5" />
                    {tr.saveAsQuestion.button}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* 存为考题 dialog：query 预填当前输入，保存成功清勾选继续标注（不跳视图） */}
      <EvalSaveQuestionDialog
        defaultPaths={defaultSavePaths}
        kbId={kbId}
        onOpenChange={setSaveOpen}
        onSaved={() => {
          setSelectedChunks([]);
          setSelectedCards([]);
        }}
        open={saveOpen}
        prefillQuery={query}
        selectionCount={selectionCount}
        selectedChunkIds={selectedChunks.map((item) => item.id)}
      />
    </div>
  );
}
