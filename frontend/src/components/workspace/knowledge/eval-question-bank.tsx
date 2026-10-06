"use client";

/**
 * 题库视图（2026-08-27 spec §4.3，plan Task 6）：题目表格 + 详情 drawer +
 * 添加 dialog + 删除二次确认。造题主入口在召回测试面板「存为考题」（§7.1），
 * 这里的「添加考题」是辅助路径——简化表单不收锚定（§4.4），无锚定题走
 * Layer 1 既有降级语义（仅参与路径判定）。编辑不支持（§4.2 规则 5）：改题
 * = 删了重加。2026-08-29 UX 修订：造题入口按钮（添加/从文档生成）并入
 * eval-tab 常驻工具栏，本组件的添加/合成 dialog 改受控（addOpen/
 * synthesisOpen 由上层下发）；原工具行与表格尾部虚线按钮均移除。
 * 2026-09-01 B 方案：首列复选框选题（双档携 question_ids，部分运行不隔离，
 * 照常进总览/趋势）。2026-09-02 批量运行栏退役：选题集上提 eval-tab 受控，
 * 工具栏运行键原位切换携 question_ids；行右键菜单承接快速评测/取消选择/
 * 删除所选（结构节奏同文档右键菜单规范）。
 */
import { ArrowUpDown, Check, Info, Layers, MoreHorizontal, Play, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AnchorBlockNotice } from "@/components/workspace/knowledge/anchor-block-notice";
import { useI18n } from "@/core/i18n/hooks";
import type { SortDirection } from "@/core/knowledge/document-view";
import { refDocIds } from "@/core/knowledge/format";
import {
  useDeleteEvalQuestion,
  useDocuments,
  useEvalQuestions,
  useMetricsOverview,
} from "@/core/knowledge/hooks";
import type { EvalQuestion, EvalTriggerInput } from "@/core/knowledge/types";

import { EvalAddQuestionDialog } from "./eval-add-question-dialog";
import { EvalQuestionDrawer } from "./eval-question-drawer";
import { EvalSynthesisDialog } from "./eval-synthesis-dialog";
import { EvalSynthesisReview } from "./eval-synthesis-review";
import { toast } from "./kb-toast";
import { runAfterMenuClose } from "./run-after-menu-close";

/** 吸顶表头单元格公共类（2026-09-02）：粘性 + 不透明底 + inset 阴影发丝线；
    h-9 钉死单元格高（与文档表头 36px 对齐）——单元格自然高（复选框 +
    内边距 ≈ 36.44）会撑破 tr 的 h-9，钉到单元格层才是唯一裁决者。
    字色钉 muted：ui/table 默认的 text-foreground 会压过 tr 的继承，
    「表头浅灰、内容深色」的层级语言（文档表 08-31 规范）从未生效——
    钉到单元格层才真正兑现。 */
const STICKY_HEAD = "sticky top-0 z-10 h-9 bg-background text-muted-foreground shadow-[inset_0_-1px_0_var(--border)]";

/** 召回率@k 三态点（2026-09-07）：全=emerald / 部分=lime / 未命中=destructive——
    与总览胶囊档位同色系（emerald/lime/orange），零召回升格 destructive：
    未命中是失败态，与回归徽章同源。 */
function recallDotClass(recall: number): string {
  if (recall >= 1) return "bg-emerald-500";
  if (recall > 0) return "bg-lime-500";
  return "bg-destructive";
}

/** 数值语言与总览对齐（2026-09-05）：指标百分数 1 位小数。 */
const percent = (value: number): string => `${(value * 100).toFixed(1)}%`;

/** 表格区 flex 子项公共类（2026-09-07 底部停靠审核容器）：与审核容器展开态
    flex-1 成 2:1 分高（审核 ≈ 1/3，检索测试路容器范式）；审核收起/空态时
    grow 独占全高。滚动由 ScrollArea 承接（2026-09-08 对齐隐式设计：overlay
    滚动条只滚动时浮现、停 2s 淡出、不占布局宽度，同百科 Tab 容器）。 */
const TABLE_AREA = "min-h-0 flex-[2]";

/** 题库排序键（2026-09-07）：default = golden.jsonl 原序（不参与排序，
    题目无 created_at 字段，原序即入库序）；其余四键与可见列一一对应。 */
type QuestionSortKey = "default" | "query" | "category" | "refDocs" | "recall";

export interface EvalQuestionBankProps {
  kbId: string;
  /** keep-alive 懒门控（eval tab 激活才发请求）。 */
  enabled?: boolean;
  /** ↗ 复现：携带 query 跳召回测试面板预填（page 层通道，§7.2）。 */
  onReproduce?: (query: string) => void;
  /** 添加考题 dialog 受控开关（2026-08-29：入口按钮在 eval-tab 常驻工具栏）。 */
  addOpen?: boolean;
  onAddOpenChange?: (open: boolean) => void;
  /** 合成触发 dialog 受控开关（同上）。 */
  synthesisOpen?: boolean;
  onSynthesisOpenChange?: (open: boolean) => void;
  /** 搜索过滤词（2026-08-30：搜索框在 eval-tab 常驻工具栏，纯前端包含匹配）。 */
  searchQuery?: string;
  onSearchQueryChange?: (query: string) => void;
  /** 选题集受控（2026-09-02 批量运行栏退役）：eval-tab 持有状态——
      工具栏原位切换要读选中态，本层右键菜单消费/清理。 */
  selectedIds: ReadonlySet<string>;
  onSelectedIdsChange: (next: ReadonlySet<string>) => void;
  /** 评测触发统一上收（2026-09-06 验收缺口修复）：右键/行菜单的评测入口委托
      eval-tab 的 handleTrigger——后者 onSuccess 里有乐观置位 in_flight 与
      pendingFullRun 记档，本层自持 mutation 会绕过它们导致头部按钮不转运行态。 */
  onTrigger: (input: EvalTriggerInput) => void;
}

export function EvalQuestionBank({
  kbId,
  enabled = true,
  onReproduce,
  addOpen = false,
  onAddOpenChange = () => undefined,
  synthesisOpen = false,
  onSynthesisOpenChange = () => undefined,
  searchQuery = "",
  selectedIds,
  onSelectedIdsChange,
  onTrigger,
}: EvalQuestionBankProps) {
  const { t } = useI18n();
  const rtk = t.knowledge;
  const etk = t.knowledge.eval;
  const qtk = etk.questions;
  const stk = etk.selection;
  const query = useEvalQuestions(kbId, enabled);
  const deleteMutation = useDeleteEvalQuestion(kbId);
  // 参考文档列 tooltip 的文档标题（与文档 tab 同 queryKey，缓存命中不新增请求）。
  const docsQuery = useDocuments(kbId);
  // 召回率@k 列数据源（2026-09-07）：最近一次 completed run 的逐题 slim 指标，
  // 与总览同 queryKey（useMetricsOverview），无新端点无新请求。
  const overview = useMetricsOverview(kbId, enabled);

  const [drawerQuestionId, setDrawerQuestionId] = useState<string | null>(null);
  // 删除目标改数组（2026-09-02）：行内删除/drawer 删除 = 单元素，
  // 右键「删除所选」= 选中集；同一二次确认对话框承接。
  const [deleteTargets, setDeleteTargets] = useState<EvalQuestion[] | null>(null);

  // 搜索过滤（2026-08-30）：题目文本不区分大小写包含匹配；题库数据已全量拉取，纯前端。
  const trimmedSearch = searchQuery.trim().toLowerCase();
  const allQuestions = useMemo(() => query.data?.questions ?? [], [query.data]);
  const visibleQuestions = trimmedSearch
    ? allQuestions.filter((question) => question.query.toLowerCase().includes(trimmedSearch))
    : allQuestions;

  // drawer 题目按 id 从列表现取（2026-10-06 改锚对）：改锚保存成功后题库缓存
  // 失效重拉，抽屉随之拿到新锚定集/悬空派生——不留陈旧副本。
  const drawerQuestion =
    drawerQuestionId !== null
      ? (allQuestions.find((question) => question.id === drawerQuestionId) ?? null)
      : null;

  // 数据刷新后剔除已不存在的选中（删除/刷新不残留幽灵选择）。
  useEffect(() => {
    const alive = allQuestions.filter((question) => selectedIds.has(question.id));
    if (alive.length !== selectedIds.size) {
      onSelectedIdsChange(new Set(alive.map((question) => question.id)));
    }
  }, [allQuestions, selectedIds, onSelectedIdsChange]);

  // doc_id → 标题映射；取不到标题回退 doc_id 前 8 位（tooltip 与抽屉组头共用）。
  const docTitles = useMemo(() => {
    const titles = new Map<string, string>();
    for (const doc of docsQuery.data ?? []) titles.set(doc.id, doc.name);
    return titles;
  }, [docsQuery.data]);
  const docTitle = (docId: string) => docTitles.get(docId) ?? docId.slice(0, 8);

  // 逐题指标按 id 索引（2026-09-07 修：改 join 跨 run 合并的 question_results——
  // 只取 latest run 的 questions 会被 scoped run 覆盖成子集，已出数的题消失）；
  // 旧网关无此键 → 空 Map → 召回列全 —。
  const questionMetrics = useMemo(() => {
    const list = overview.data?.question_results;
    return new Map((list ?? []).map((metric) => [metric.id, metric]));
  }, [overview.data]);

  // 排序（2026-09-07）：内容逻辑与文档 tab 排序菜单同构（键 + 方向，纯
  // 前端稳定排序）；形态挪到表头最右悬浮按钮（文档 tab 列显隐钮同款），
  // 题库无可隐藏列，该钮只承接排序。初始 default：不默默重排既有视图。
  const [sort, setSort] = useState<{ key: QuestionSortKey; direction: SortDirection }>({ key: "default", direction: "asc" });

  // 菜单项标签复用列头词汇（召回键随 top_k 动态，召回率@5）；refDocs 例外
  // （2026-10-06 列口径改造）：比较器按去重文档数落（跨文档广度），与格子
  // 显示的切片数不同轴——label 明义那根轴叫「文档数」。
  const sortOptions: { key: QuestionSortKey; label: string }[] = [
    { key: "default", label: qtk.sortDefault },
    { key: "query", label: qtk.columnQuery },
    { key: "category", label: qtk.columnCategory },
    { key: "refDocs", label: qtk.sortDocsCount },
    { key: "recall", label: etk.tableRecallAtK(overview.data?.layer1?.metrics.top_k ?? null) },
  ];

  const sortedQuestions = useMemo(() => {
    if (sort.key === "default") return visibleQuestions;
    const sign = sort.direction === "asc" ? 1 : -1;
    const value = (question: EvalQuestion): string | number | null => {
      switch (sort.key) {
        case "query":
          return question.query.toLowerCase();
        case "category":
          // 按显示名排（非 wire 键）：用户看到什么就按什么排。
          return etk.category[question.category];
        case "refDocs":
          // 排序轴 = 去重文档数（跨文档广度——哪些题锚跨多篇即综合题）；
          // 2026-10-06 他裁保篇序，比较器不随格子显示的切片数改。
          return refDocIds(question.relevant_chunk_ids).length;
        case "recall":
          return questionMetrics.get(question.id)?.recall ?? null;
        default:
          return null;
      }
    };
    return [...visibleQuestions].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      // 未测题（recall null）恒沉底，不随方向翻转——同文档 tab
      // sortDocuments 的 null-sink 纪律。
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string" && typeof bv === "string") return sign * av.localeCompare(bv);
      return sign * (Number(av) - Number(bv));
    });
  }, [visibleQuestions, sort, questionMetrics, etk]);

  const toggleQuestion = (questionId: string, checked: boolean) => {
    const next = new Set(selectedIds);
    if (checked) next.add(questionId);
    else next.delete(questionId);
    onSelectedIdsChange(next);
  };

  const allVisibleSelected = visibleQuestions.length > 0 && visibleQuestions.every((question) => selectedIds.has(question.id));

  const toggleSelectAllVisible = () => {
    const next = new Set(selectedIds);
    if (allVisibleSelected) visibleQuestions.forEach((question) => next.delete(question.id));
    else visibleQuestions.forEach((question) => next.add(question.id));
    onSelectedIdsChange(next);
  };

  // 评测触发委托 eval-tab（onTrigger → handleTrigger）：乐观置位/档位记档/清选择
  // 均由上层 onSuccess 统一处理，本层不再自持 trigger mutation。
  const handleBulkTrigger = (input: EvalTriggerInput) => {
    onTrigger(input);
  };

  // 文件管理器惯例：右键未选中行只选中该行；右键已选中行保持批量上下文。
  const handleRowContextMenu = (questionId: string) => {
    if (!selectedIds.has(questionId)) {
      onSelectedIdsChange(new Set([questionId]));
    }
  };

  const selectedQuestions = () => allQuestions.filter((question) => selectedIds.has(question.id));

  const handleDeleteConfirm = async () => {
    if (deleteTargets === null) return;
    const removed = new Set(deleteTargets.map((question) => question.id));
    const results = await Promise.allSettled(deleteTargets.map((question) => deleteMutation.mutateAsync(question.id)));
    if (results.some((result) => result.status === "rejected")) {
      toast.error(qtk.deleteFailed);
    } else {
      toast.success(qtk.deletedToast);
    }
    onSelectedIdsChange(new Set([...selectedIds].filter((id) => !removed.has(id))));
    setDeleteTargets(null);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 批量运行栏退役（2026-09-02）：插入式条推挤表格产生抖动；选题运行
          由工具栏原位切换承接（运行所选/完整运行所选），取消选择/删除所选
          进行右键菜单 */}

      <ScrollArea className={TABLE_AREA} horizontal scrollHideDelay={2000} type="scroll">
      {query.isLoading ? (
        <div className="text-muted-foreground mx-4 rounded-lg border border-dashed p-6 text-center text-sm">
          {etk.loading}
        </div>
      ) : query.error ? (
        <div className="text-destructive mx-4 rounded-lg border border-dashed p-6 text-center text-sm">
          {etk.loadFailed}
        </div>
      ) : query.data && allQuestions.length > 0 ? (
        visibleQuestions.length === 0 ? (
          /* 无匹配（2026-08-30 搜索）：区别于空库引导——库里有题但过滤词无命中 */
          <div className="text-muted-foreground mx-4 rounded-lg border border-dashed p-6 text-center text-sm">
            {qtk.noMatch}
          </div>
        ) : (
        /* 表格样式对齐文档列表（2026-08-30）：表头去默认 h-10 降为 text-xs 自然高（32px），
           数据行同文档列表 px-2 py-2（36px）；松垮根源是 h-10 表头与行尾大图标按钮；
           表头同文档列表用 muted 色。吸顶（2026-09-02）：表头单元格 sticky + inset
           阴影发丝线（折叠模式下 tr 边框随滚动丢失）；纵/横滚由表格区 ScrollArea
           承接（2026-09-08 隐式 overlay 滚动条对齐，Viewport 为吸顶滚动祖先） */
        <Table containerClassName="relative w-full">
          <TableHeader className="[&_tr]:border-0 [&_tr]:text-muted-foreground">
            {/* h-9 钉高与文档表头对齐（36px，2026-09-02）；th 自然高低于 36，
                行高由 tr 裁决；发丝线是 th 的 inset 阴影（不参与布局），
                复选框状态切换不会引起表头高度重取整。 */}
            <TableRow className="group/colhead h-9">
              {/* 首列复选框 px-2 与文档表头对齐（2026-09-02）：复选框是悬浮即现的
                  瞬态控件，跨 tab 位置一致比找齐工具栏边距更重要；行复选框同文档表：
                  悬停/勾选/任一选中才显形，静止态不抢戏 */}
              <TableHead className={`${STICKY_HEAD} w-8 px-2`}>
                {/* 内层 flex 几何居中（2026-09-02）：与文档表头复选框同位；不给 th 自身挂
                    flex（th 会脱出表格布局），钉死 h-9 与表头等高 */}
                <div className="flex h-9 items-center">
                  <Checkbox aria-label={stk.selectAllAria} checked={allVisibleSelected} onCheckedChange={() => toggleSelectAllVisible()} />
                </div>
              </TableHead>
              <TableHead className={`${STICKY_HEAD} px-2 text-xs`}>{qtk.columnQuery}</TableHead>
              <TableHead className={`${STICKY_HEAD} px-2 text-xs`}>{qtk.columnCategory}</TableHead>
              {/* 参考切片列头（2026-10-06 列口径改造：单位进表头、格子纯数字
                  = 切片数）：数值列右对齐，与文档 tab 数值列（text-right
                  tabular-nums）同轴语言。 */}
              <TableHead className={`${STICKY_HEAD} px-2 text-right text-xs`}>{qtk.columnRefChunks}</TableHead>
              {/* 召回率@k 列头（2026-09-07 表头重设计）：复用总览既有指标词汇
                  （零新词），时间口径进 ⓘ tooltip——同总览「表头=指标名、
                  tooltip=口径解释」模式；数值列右对齐与数据同轴。 */}
              <TableHead className={`${STICKY_HEAD} px-2 text-right text-xs`}>
                <span className="inline-flex items-center gap-1">
                  {etk.tableRecallAtK(overview.data?.layer1?.metrics.top_k ?? null)}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label={qtk.columnRecallNote}
                        className="text-muted-foreground inline-flex hover:text-foreground"
                      >
                        <Info className="size-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-60 text-pretty">{qtk.columnRecallNote}</TooltipContent>
                  </Tooltip>
                </span>
              </TableHead>
              {/* 表头最右悬浮排序钮（2026-09-07）：形态 = 文档 tab 列显隐钮同款
                  （悬停现形 size-6，聚焦/菜单开常驻），内容 = 文档 tab 排序菜单同构
                  （Label + 键勾选 + 分隔线 + 升/降序恒常展示）。默认排序态隐形不扰，
                  排序激活后常驻可见——「当前有排序 + 入口在哪」随时可追溯；默认态
                  选方向只记档（原序无方向可排），切真实排序键时即生效。 */}
              <TableHead className={`${STICKY_HEAD} w-10 pr-4 pl-2`}>
                <div className="flex h-9 items-center justify-end">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label={rtk.sortDocuments}
                        className={`text-muted-foreground hover:text-foreground flex size-6 items-center justify-center rounded transition-opacity focus-visible:opacity-100 has-[[data-state=open]]:opacity-100 ${sort.key === "default" ? "opacity-0 group-hover/colhead:opacity-100" : "opacity-100"}`}
                      >
                        <ArrowUpDown className="size-4" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuLabel>{rtk.sortDocuments}</DropdownMenuLabel>
                      {sortOptions.map((option) => (
                        <DropdownMenuItem key={option.key} onSelect={() => setSort((current) => ({ ...current, key: option.key }))}>
                          <Check className={`size-4 ${sort.key !== option.key ? "invisible" : ""}`} />
                          {option.label}
                        </DropdownMenuItem>
                      ))}
                      <DropdownMenuSeparator />
                      {(["asc", "desc"] as const).map((direction) => (
                        <DropdownMenuItem key={direction} onSelect={() => setSort((current) => ({ ...current, direction }))}>
                          <Check className={`size-4 ${sort.direction !== direction ? "invisible" : ""}`} />
                          {rtk.sort[direction]}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedQuestions.map((question) => {
              const isSelected = selectedIds.has(question.id);
              const docIds = refDocIds(question.relevant_chunk_ids);
              const metric = questionMetrics.get(question.id);
              const recall = metric?.recall ?? null;
              return (
              <ContextMenu key={question.id}>
                <ContextMenuTrigger asChild>
              {/* 行间去分割线（2026-09-02）：ui/table 行默认 border-b，与文档表
                  08-31「无框表、结构线只留表头发丝线」的决策不一致——文档行早已去掉
                  border-b，题库行却仍带，题目间那条线就是它。去掉后两表数据行同为
                  px-2 py-2 无框行，行高同基准（collapse 模式下这条内边框还会挤进
                  行间，一并收掉）。 */}
              <TableRow
                className="group cursor-pointer border-0"
                onClick={() => setDrawerQuestionId(question.id)}
                onContextMenu={() => handleRowContextMenu(question.id)}
              >
                {/* 选题复选框（B 方案）：单元格 stopPropagation，勾选不开详情 drawer；
                    显隐同文档表（2026-09-02）：悬停/勾选/任一选中才显形 */}
                <TableCell className="w-8 px-2 py-2" onClick={(event) => event.stopPropagation()}>
                  <Checkbox
                    aria-label={stk.rowSelectAria(question.query)}
                    checked={selectedIds.has(question.id)}
                    className={`opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100 ${selectedIds.size > 0 ? "opacity-100" : ""}`}
                    onCheckedChange={(checked) => toggleQuestion(question.id, checked === true)}
                  />
                </TableCell>
                <TableCell className="max-w-52 px-2 py-2">
                  {/* 悬浮统一（2026-10-06）：原生 title 换项目 Tooltip（与文档名
                      tooltip 同款 Radix 主题样式）。 */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="block truncate cursor-default">
                        {question.query}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-60 text-pretty">
                      {question.query}
                    </TooltipContent>
                  </Tooltip>
                </TableCell>
                <TableCell className="px-2 py-2">
                  {/* 胶囊盒体与列网格线齐线（2026-09-08 八轮用户纠正，历史表环境
                      列同款）：-ml-2 退役——盒体边缘才是对齐主体。 */}
                  <Badge variant="outline">{etk.category[question.category]}</Badge>
                </TableCell>
                {/* 参考切片格（2026-10-06 列口径改造：数字与中文量词不在数值格
                    混排）：纯数字 = 切片数（与抽屉「N 切片」徽章同数同口径）；
                    hover 仍列文档名（篇数 = 列表行数，不再单列）。悬空徽章
                    （spec §2②）：missing_chunk_ids 非空才显、纯词无数字无图标
                    （对齐「检测到回退」先例）；无锚定题空单元格，与召回列 —
                    互相呼应（无锚定题不参与命中率计算）。 */}
                <TableCell className="px-2 py-2 text-right tabular-nums">
                  <span className="inline-flex items-center justify-end gap-1.5">
                    {question.relevant_chunk_ids.length > 0 && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-default">
                            {question.relevant_chunk_ids.length}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-60 text-pretty whitespace-pre-wrap">
                          {docIds.map(docTitle).join("\n")}
                        </TooltipContent>
                      </Tooltip>
                    )}
                    {(question.missing_chunk_ids?.length ?? 0) > 0 && (
                      <Badge className="shrink-0 px-1.5 text-[10px]" variant="destructive">
                        {qtk.danglingBadge}
                      </Badge>
                    )}
                    {/* 落空「存疑」徽章（spec §2④，B1=甲）：anchor_mismatch 非空
                        才显、纯词无数字无图标；amber 档＝可确认待人看（悬空
                        destructive 档＝已坏不可绕）。悬浮＝项目 Tooltip 机器
                        依据（红块同款文案：缺失术语/建议锚/命中表）。 */}
                    {question.anchor_mismatch != null && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-default">
                            <Badge
                              className="shrink-0 border-amber-500/40 px-1.5 text-[10px] text-amber-700 dark:text-amber-500"
                              variant="outline"
                            >
                              {qtk.mismatchBadge}
                            </Badge>
                          </span>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-60">
                          <AnchorBlockNotice detail={question.anchor_mismatch} />
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </span>
                </TableCell>
                {/* 召回率@k 列（2026-09-07）：跨 run 合并的逐题最近结果（三态点+
                    百分比）；未测显 —；单元格 tooltip 带实际路径（未命中时即
                    分诊线索）。 */}
                <TableCell className="px-2 py-2 text-right tabular-nums">
                  {recall === null ? (
                    <span aria-label={qtk.recallUntested} className="text-muted-foreground">
                      —
                    </span>
                  ) : (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="inline-flex cursor-default items-center justify-end gap-1.5">
                          <span className={`size-1.5 rounded-full ${recallDotClass(recall)}`} />
                          {percent(recall)}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-60 text-pretty">
                        {qtk.recallTip(percent(recall), metric?.actual_path ?? "-")}
                      </TooltipContent>
                    </Tooltip>
                  )}
                </TableCell>
                {/* 末列悬浮三点（2026-09-02）：替换原 size-8（32px）删除按钮——它是题库行
                    48px 的裁决者，比文档行（40px，由三点 size-6=24px 撑起）高 8px；换成
                    文档 tab 同款 size-6 三点后行高落到 40px，两表逐像素对齐。菜单镜像右键的
                    行级子集：快速评测 / 完整评测 / 删除（行级语义，不依赖选择态）；
                    hover/选中/聚焦/菜单开时淡入，静止态不抢戏（同文档表三点）。 */}
                <TableCell className="w-10 py-2 pr-4 pl-1 text-right" onClick={(event) => event.stopPropagation()}>
                  <div
                    className={`flex justify-end transition-opacity opacity-0 group-hover:opacity-100 focus-within:opacity-100 has-[[data-state=open]]:opacity-100 ${isSelected ? "opacity-100" : ""}`}
                    data-testid="bank-row-more"
                  >
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button aria-label={rtk.moreActions} className="size-6" size="icon" variant="ghost">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-44">
                        <DropdownMenuItem onSelect={() => handleBulkTrigger({ layers: "l1", question_ids: [question.id] })}>
                          <Play className="size-4" />
                          {etk.tierQuick}
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => handleBulkTrigger({ layers: "l1_l2", question_ids: [question.id] })}>
                          <Layers className="size-4" />
                          {etk.tierFull}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onSelect={() => setDeleteTargets([question])}>
                          <Trash2 className="size-4" />
                          {qtk.rowDelete}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </TableCell>
              </TableRow>
                </ContextMenuTrigger>
                <ContextMenuContent className="w-44">
                  {isSelected && selectedIds.size > 1 ? (
                    <>
                      <ContextMenuLabel>{rtk.selectedCount(selectedIds.size)}</ContextMenuLabel>
                      {/* 结构节奏同文档右键菜单（2026-09-02 定稿）：普通动作 →
                          取消选择（X）→ 分隔线 → 危险操作沉底单独隔离；
                          快速评测 = L1 档携选中集 question_ids */}
                      <ContextMenuItem onSelect={() => handleBulkTrigger({ layers: "l1", question_ids: [...selectedIds] })}>
                        <Play className="size-4" />
                        {etk.tierQuick}
                      </ContextMenuItem>
                      <ContextMenuItem onSelect={() => handleBulkTrigger({ layers: "l1_l2", question_ids: [...selectedIds] })}>
                        <Layers className="size-4" />
                        {etk.tierFull}
                      </ContextMenuItem>
                      <ContextMenuItem onSelect={() => onSelectedIdsChange(new Set())}>
                        <X className="size-4" />
                        {rtk.cancelSelection}
                      </ContextMenuItem>
                      <ContextMenuSeparator />
                      <ContextMenuItem
                        variant="destructive"
                        onSelect={() => runAfterMenuClose(() => setDeleteTargets(selectedQuestions()))}
                      >
                        <Trash2 className="size-4" />
                        {rtk.deleteSelected}
                      </ContextMenuItem>
                    </>
                  ) : (
                    <>
                      {/* 单选：快速/完整评测只跑该题；右键即选中，退出/删除措辞两态对称 */}
                      <ContextMenuItem onSelect={() => handleBulkTrigger({ layers: "l1", question_ids: [question.id] })}>
                        <Play className="size-4" />
                        {etk.tierQuick}
                      </ContextMenuItem>
                      <ContextMenuItem onSelect={() => handleBulkTrigger({ layers: "l1_l2", question_ids: [question.id] })}>
                        <Layers className="size-4" />
                        {etk.tierFull}
                      </ContextMenuItem>
                      <ContextMenuItem onSelect={() => onSelectedIdsChange(new Set())}>
                        <X className="size-4" />
                        {rtk.cancelSelection}
                      </ContextMenuItem>
                      <ContextMenuSeparator />
                      <ContextMenuItem
                        variant="destructive"
                        onSelect={() => runAfterMenuClose(() => setDeleteTargets([question]))}
                      >
                        <Trash2 className="size-4" />
                        {rtk.deleteSelected}
                      </ContextMenuItem>
                    </>
                  )}
                </ContextMenuContent>
              </ContextMenu>
              );
            })}
          </TableBody>
        </Table>
        )
      ) : (
        <div className="text-muted-foreground mx-4 rounded-lg border border-dashed p-6 text-center text-sm">
          <p>{qtk.emptyBank}</p>
          {/* 双入口第二句（2026-08-28 §7）：合成造题引导 */}
          <p>{qtk.emptyBankSynthesis}</p>
        </div>
      )}
      </ScrollArea>

      {/* 候选审核（2026-09-07 底部停靠、2026-09-08 常驻）：无候选收为单行头
          承载空态/上次合成元信息，有候选展开 1/3 高内滚；采纳的题即刻出现
          在正上方表格——任务与结果邻接。 */}
      <EvalSynthesisReview enabled={enabled} kbId={kbId} />

      {/* 添加/合成 dialog 受控（2026-08-29）：入口按钮在 eval-tab 常驻工具栏；
          批量完整评测确认已上提 eval-tab（工具栏原位切换，2026-09-02） */}
      <EvalAddQuestionDialog kbId={kbId} open={addOpen} onOpenChange={onAddOpenChange} />

      {/* 合成触发 dialog：文档 + 数量 → 202 幂等，候选落暂存待审 */}
      <EvalSynthesisDialog kbId={kbId} open={synthesisOpen} onOpenChange={onSynthesisOpenChange} />

      {/* 详情 drawer：行点击下钻（§4.5）；onDelete 关 drawer 再开确认框 */}
      <EvalQuestionDrawer
        kbId={kbId}
        onDelete={(question) => {
          setDrawerQuestionId(null);
          setDeleteTargets([question]);
        }}
        onOpenChange={(open) => {
          if (!open) setDrawerQuestionId(null);
        }}
        onReproduce={onReproduce}
        open={drawerQuestion !== null}
        question={drawerQuestion}
      />

      {/* 删除二次确认（§4.3）：单条展示 query 全文，批量展示已选计数；删除后不可恢复 */}
      <Dialog onOpenChange={(open) => !open && setDeleteTargets(null)} open={deleteTargets !== null}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{qtk.deleteConfirm.title}</DialogTitle>
            <DialogDescription>
              {deleteTargets?.length === 1 ? deleteTargets[0]?.query : rtk.selectedCount(deleteTargets?.length ?? 0)}
              <br />
              {qtk.deleteConfirm.description}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setDeleteTargets(null)} variant="outline">
              {qtk.deleteConfirm.cancel}
            </Button>
            <Button onClick={handleDeleteConfirm} variant="destructive">
              {qtk.deleteConfirm.confirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
