"use client";

/**
 * 历史视图（2026-08-27 spec §6.2，plan Task 7；2026-09-08 表格化 + 代号
 * 退役；二轮对齐题库表）：运行列表表格——与题库/文档表同骨架（无框行
 * + 吸顶表头发丝线，表头浅灰/内容深色；表头 tr h-9 + th text-xs 与题库
 * 表头同高同字号）。五列：运行时间（回退=红/基线=琥珀胶囊 + mono 时间 +
 * 完整时间 tooltip；基线星四轮退役）| 环境（胶囊 -ml-2 文字与表头同轴）|
 * 评测内容（档位短词快速/完整；L1/L2 代号界面禁现）
 * | 状态（图标+短文案）| 时长（左对齐，dur* 紧凑词汇与 banner 摘要同源）。
 * 七轮定案（照抄题库配方）：内容列全部不钉宽——剩余宽按内容比例均摊呼吸；
 * 八轮补边缘工具列（删除功能）：首列复选框 w-8 + 末列悬浮三点 w-10 钉宽
 * （题库同款边缘工具列钉宽纪律）。八轮对齐修正：胶囊盒体与列网格线齐线
 * （-ml-2 全量退役——芯片内边距是芯片自己的语言，盒体边缘才参与列对齐）；
 * 时长改右对齐数值列（同题库参考文档/召回率右轴语言）。回退/基线信息收进运行
 * 时间列胶囊色
 * （三轮用户定案：回退=红、基线=琥珀，检索耗时胶囊同族；状态列回退红
 * Badge 退役——占列表空间）。
 * 行点击经 ``onOpenRun`` 复用 eval-tab 持有的 EvalRunDrawer 实例（与趋势
 * 图点数据点同一下钻出口，零新 drawer）。skipped/error 行不进
 * latest/trend——历史是它们的唯一曝光面；in-flight 运行不产生伪行
 * （运行中状态只由工具栏 spinner 表达，行在落库后才出现）。
 */
import { ArrowUpDown, Ban, Check, CheckCircle2, ChevronDown, MoreHorizontal, SkipForward, Trash2, X, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useI18n } from "@/core/i18n/hooks";
import type { SortDirection } from "@/core/knowledge/document-view";
import {
  durationParts,
  runDurationSeconds,
} from "@/core/knowledge/eval-run-status";
import { formatKnowledgeTimestamp } from "@/core/knowledge/format";
import { useDeleteEvalRuns, useEvalRuns } from "@/core/knowledge/hooks";
import type { EvalRunSummary } from "@/core/knowledge/types";

import { toast } from "./kb-toast";
import { runAfterMenuClose } from "./run-after-menu-close";

export interface EvalRunHistoryProps {
  kbId: string;
  /** keep-alive 懒门控（eval tab 激活才发请求；与工具栏共享同一 query 缓存）。 */
  enabled?: boolean;
  /** 行点击下钻：携带 runId，由 eval-tab 的 setDrawerRunId 承接。 */
  onOpenRun: (runId: string) => void;
}

/** 行内时间：MM-DD HH:mm（spec §6.2 ASCII 示例口径）；缺失/非法 → "-"。 */
export function formatRunTime(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 吸顶表头（题库/文档表同款配方 2026-09-02）：sticky + inset 阴影发丝线；
    滚动祖先 = eval-tab 视图区 ScrollArea。 */
const STICKY_HEAD =
  "sticky top-0 z-10 h-9 bg-background text-muted-foreground shadow-[inset_0_-1px_0_var(--border)]";

/** 运行时间列胶囊色系（2026-09-08 三轮用户定案）：回退=红、基线=琥珀——
    检索测试耗时胶囊同族（bg-x-500/10 text-x-700 dark 提亮），同列兄弟胶囊
    同形同透明度；回退优先于基线（基线 run 也可能检测到回退）。 */
const REGRESSION_TIME_TONE = "bg-red-500/10 text-red-700 dark:text-red-300";
const BASELINE_TIME_TONE = "bg-amber-500/10 text-amber-700 dark:text-amber-300";

/** 排序键（九轮，题库同构）：default = 服务端 created_at 倒序原序。 */
type RunSortKey = "default" | "time" | "env" | "scope" | "status" | "duration";

/** 时长格式（九轮，文档 tab 时间表头同款下拉）：compact = dur* 紧凑词汇；
    seconds = 全量秒。 */
type DurationFormat = "compact" | "seconds";

export function EvalRunHistory({
  kbId,
  enabled = true,
  onOpenRun,
}: EvalRunHistoryProps) {
  const { t, locale } = useI18n();
  const rtk = t.knowledge;
  const etk = t.knowledge.eval;
  const qtk = etk.questions;
  const stk = etk.selection;
  const htk = etk.history;
  const query = useEvalRuns(kbId, enabled);
  const deleteMutation = useDeleteEvalRuns(kbId);

  // 删除功能选中集（2026-09-08）：历史内部自持（选题集上提 eval-tab 是因为
  // 工具栏要读，历史选中只服务删除，无需上提）。
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set());
  const [deleteTargets, setDeleteTargets] = useState<string[] | null>(null);
  // 排序（九轮，题库同构）：default = 服务端 created_at 倒序（不默默重排既有
  // 视图）；其余键与可见列一一对应。
  const [sort, setSort] = useState<{ key: RunSortKey; direction: SortDirection }>({ key: "default", direction: "asc" });
  // 时长格式（九轮，文档 tab 时间表头同款下拉）：compact = dur* 紧凑词汇
  // （现状默认）/ seconds = 全量秒。
  const [durationFormat, setDurationFormat] = useState<DurationFormat>("compact");
  // useMemo 钉引用（eslint react-hooks）：?? [] 每渲染新引用会使 prune effect
  // 依赖每渲染变动。
  const runs = useMemo(() => query.data?.runs ?? [], [query.data]);
  // 数据刷新后剔除已不存在的选中（删除/刷新不残留幽灵选择，同题库）。
  useEffect(() => {
    const alive = runs.filter((run) => selectedIds.has(run.run_id));
    if (alive.length !== selectedIds.size) {
      setSelectedIds(new Set(alive.map((run) => run.run_id)));
    }
  }, [runs, selectedIds]);

  const envLabel = useCallback(
    (run: EvalRunSummary) =>
      run.environment === "ci"
        ? htk.envCi
        : run.environment === "nightly"
          ? htk.envNightly
          : htk.envLocal,
    [htk],
  );
  // 评测内容（2026-09-08 代号退役 + 二三轮用户定案）：L1/L2 内部代号界面禁现；
  // 档位短词快速/完整（三轮去「评测」尾缀——列头已承载语义），与工具栏两
  // 按钮同根词汇；仅跑生成的残 run 诚实回退「生成」；双层未跑（skipped/
  // cancelled 半途）显破折号不假报内容。
  const scopeLabel = useCallback(
    (run: EvalRunSummary) =>
      run.has_layer1 && run.has_layer2
        ? htk.scopeFull
        : run.has_layer1
          ? htk.scopeQuick
          : run.has_layer2
            ? htk.scopeGeneration
            : null,
    [htk],
  );
  // 时长列（2026-09-08 二轮 + 九轮格式下拉 + 十轮按秒取整）：compact = banner
  // 摘要同款 dur* 紧凑词汇；seconds = 全量秒且**整数**（用户十轮纠正：不要
  // 小数——Math.round 与 durationParts 同取整口径）；缺戳/倒序 → null →
  // 破折号（不显假数字）。
  const durationText = (run: EvalRunSummary) => {
    const secs = runDurationSeconds(run);
    if (secs === null) return null;
    if (durationFormat === "seconds") return etk.durSeconds(Math.round(secs));
    const parts = durationParts(secs);
    return parts.kind === "seconds"
      ? etk.durSeconds(parts.value)
      : parts.kind === "minutes"
        ? etk.durMinutes(parts.value)
        : etk.durMinutesSeconds(parts.minutes, parts.seconds);
  };

  // 状态短文案（九轮抽出）：渲染与排序共用同一词汇源（按显示名排非 wire 键）。
  const statusLabel = useCallback(
    (run: EvalRunSummary) =>
      run.status === "error"
        ? htk.statusError
        : run.status === "skipped"
          ? htk.statusSkipped
          : run.status === "cancelled"
            ? htk.statusCancelled
            : htk.statusCompleted,
    [htk],
  );

  // 排序（九轮，题库同构）：纯前端稳定排序；null-sink 纪律——无值行恒沉底
  // 不随方向翻转（同题库未测题/文档 tab 同方案）。
  const sortedRuns = useMemo(() => {
    if (sort.key === "default") return runs;
    const sign = sort.direction === "asc" ? 1 : -1;
    const value = (run: EvalRunSummary): string | number | null => {
      switch (sort.key) {
        case "time":
          return run.created_at ? new Date(run.created_at).getTime() : null;
        case "env":
          return envLabel(run);
        case "scope":
          return scopeLabel(run);
        case "status":
          return statusLabel(run);
        case "duration":
          return runDurationSeconds(run);
        default:
          return null;
      }
    };
    return [...runs].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string" && typeof bv === "string") return sign * av.localeCompare(bv);
      return sign * (Number(av) - Number(bv));
    });
  }, [runs, sort, envLabel, scopeLabel, statusLabel]);

  // 排序菜单项标签全量复用列头词汇（零新词，同题库）。
  const sortOptions: { key: RunSortKey; label: string }[] = [
    { key: "default", label: htk.sortDefault },
    { key: "time", label: htk.colTime },
    { key: "env", label: htk.colEnv },
    { key: "scope", label: htk.colScope },
    { key: "status", label: htk.colStatus },
    { key: "duration", label: htk.colDuration },
  ];

  // 运行时间列（2026-09-08 三轮胶囊色 + 四轮去星 + 九轮数字轴对齐）：时间列
  // 是数字列——胶囊内文字与裸行数字同轴（-ml-2 补偿盒体自带 px-2，tabular
  // 纵向对齐纪律优先于盒体网格线）；环境列是全胶囊列无裸行兄弟，盒体对齐
  // 网格线规则不变（八轮）。两列规则分化：有裸行兄弟看文字轴，无则看盒体轴。
  const renderTimeCell = (run: EvalRunSummary) => {
    const tone = run.regression_detected
      ? REGRESSION_TIME_TONE
      : run.is_baseline
        ? BASELINE_TIME_TONE
        : null;
    const timeSpan = (
      <span
        className="font-mono text-xs tabular-nums"
        title={
          run.created_at
            ? formatKnowledgeTimestamp(run.created_at, locale)
            : undefined
        }
      >
        {formatRunTime(run.created_at)}
      </span>
    );
    if (tone === null) return timeSpan;
    return (
      <span
        aria-label={run.regression_detected ? etk.regressionBadge : undefined}
        className={`-ml-2 inline-flex items-center rounded-full px-2 py-0.5 ${tone}`}
        title={run.regression_detected ? etk.regressionBadge : etk.drawer.baselineBadge}
      >
        {timeSpan}
      </span>
    );
  };

  const renderStatus = (run: EvalRunSummary) => {
    if (run.status === "error") {
      return (
        <>
          <XCircle aria-hidden className="text-destructive size-3.5 shrink-0" />
          {statusLabel(run)}
        </>
      );
    }
    if (run.status === "skipped") {
      return (
        <>
          <SkipForward aria-hidden className="text-muted-foreground size-3.5 shrink-0" />
          {statusLabel(run)}
        </>
      );
    }
    // 终止行（spec 2026-09-06 §11）：用户主动行为，muted 色调区别 error 的红。
    if (run.status === "cancelled") {
      return (
        <>
          <Ban aria-hidden className="text-muted-foreground size-3.5 shrink-0" />
          {statusLabel(run)}
        </>
      );
    }
    return (
      <>
        <CheckCircle2 aria-hidden className="size-3.5 shrink-0" />
        {statusLabel(run)}
      </>
    );
  };

  // ── 删除功能（2026-09-08，题库同构）──────────────────────────
  const toggleRun = (runId: string, checked: boolean) => {
    const next = new Set(selectedIds);
    if (checked) next.add(runId);
    else next.delete(runId);
    setSelectedIds(next);
  };

  const allVisibleSelected = runs.length > 0 && runs.every((run) => selectedIds.has(run.run_id));

  const toggleSelectAllVisible = () => {
    const next = new Set(selectedIds);
    if (allVisibleSelected) runs.forEach((run) => next.delete(run.run_id));
    else runs.forEach((run) => next.add(run.run_id));
    setSelectedIds(next);
  };

  // 文件管理器惯例：右键未选中行只选中该行；右键已选中行保持批量上下文。
  const handleRowContextMenu = (runId: string) => {
    if (!selectedIds.has(runId)) setSelectedIds(new Set([runId]));
  };

  const handleDeleteConfirm = async () => {
    if (deleteTargets === null) return;
    const removed = new Set(deleteTargets);
    try {
      await deleteMutation.mutateAsync(deleteTargets);
      toast.success(htk.deletedToast);
    } catch {
      toast.error(htk.deleteFailed);
    }
    setSelectedIds((current) => new Set([...current].filter((id) => !removed.has(id))));
    setDeleteTargets(null);
  };

  // 确认框描述数据：单条展示运行时间+环境，批量展示计数；基线警示行条件显。
  const targetRuns = (deleteTargets ?? [])
    .map((id) => runs.find((run) => run.run_id === id))
    .filter((run): run is EvalRunSummary => run !== undefined);
  const targetsIncludeBaseline = targetRuns.some((run) => run.is_baseline);

  return (
    <div className="flex flex-col gap-2">
      {query.isLoading ? (
        <div className="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm">
          {etk.loading}
        </div>
      ) : query.error ? (
        <div className="text-destructive rounded-lg border border-dashed p-6 text-center text-sm">
          {etk.loadFailed}
        </div>
      ) : query.data && query.data.runs.length > 0 ? (
        /* 全宽表 + 五列全 auto（2026-09-08 七轮照抄题库配方）：题库只钉边缘
           工具列（复选框 w-8/排序 w-10），内容列全不钉宽——剩余宽按内容比例
           均摊到每列（呼吸感而非单列大洞）；历史无边缘工具列，故五列全 auto。
           单列拉伸（六轮）退役：全部余量灌进一列 = 400px 大洞。 */
        <Table containerClassName="relative w-full">
          <TableHeader className="[&_tr]:border-0 [&_tr]:text-muted-foreground">
            {/* tr h-9 + th text-xs（2026-09-08 二轮）：题库表头同款钉高与字号——
                两表表头同高同语言，跨视图切换不跳。 */}
            <TableRow className="group/colhead h-9">
              {/* 首列复选框（2026-09-08 删除功能，题库配方）：w-8 边缘工具列钉宽；
                  复选框是悬浮即现的瞬态控件，跨表位置一致。 */}
              <TableHead className={`${STICKY_HEAD} w-8 px-2`}>
                <div className="flex h-9 items-center">
                  <Checkbox
                    aria-label={stk.selectAllAria}
                    checked={allVisibleSelected}
                    onCheckedChange={() => toggleSelectAllVisible()}
                  />
                </div>
              </TableHead>
              <TableHead className={`${STICKY_HEAD} px-2 text-xs`}>
                {htk.colTime}
              </TableHead>
              <TableHead className={`${STICKY_HEAD} px-2 text-xs`}>
                {htk.colEnv}
              </TableHead>
              <TableHead className={`${STICKY_HEAD} px-2 text-xs`}>
                {htk.colScope}
              </TableHead>
              <TableHead className={`${STICKY_HEAD} px-2 text-xs`}>
                {htk.colStatus}
              </TableHead>
              {/* 时长列（八轮右对齐 + 九轮格式下拉）：表头悬浮 ChevronDown
                  （文档 tab 时间表头同款 group/th 配方）：compact/seconds 两档
                  Check 菜单；非默认档按钮常驻可追溯。 */}
              <TableHead className={`${STICKY_HEAD} group/th px-2 text-right text-xs`}>
                <span className="inline-flex items-center gap-1">
                  {htk.colDuration}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label={htk.durFormatLabel}
                        className={`text-muted-foreground hover:text-foreground -mr-1 flex size-5 shrink-0 items-center justify-center rounded opacity-0 transition-opacity focus-visible:opacity-100 has-[[data-state=open]]:opacity-100 group-hover/th:opacity-100 ${durationFormat === "seconds" ? "opacity-100" : ""}`}
                      >
                        <ChevronDown className="size-3.5" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="w-40">
                      <DropdownMenuLabel>{htk.durFormatLabel}</DropdownMenuLabel>
                      {(["compact", "seconds"] as const).map((format) => (
                        <DropdownMenuItem key={format} onSelect={() => setDurationFormat(format)}>
                          <Check className={`size-4 ${durationFormat !== format ? "invisible" : ""}`} />
                          {format === "compact" ? htk.durFormatCompact : htk.durFormatSeconds}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </span>
              </TableHead>
              {/* 表头最右悬浮排序钮（九轮，题库同款）：形态 = 文档/题库表头钮
                  同构（悬停现形 size-6，聚焦/菜单开常驻，激活后常驻）；内容 =
                  六键 + 升/降序恒常。 */}
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
            {sortedRuns.map((run) => {
              const isSelected = selectedIds.has(run.run_id);
              return (
              <ContextMenu key={run.run_id}>
                <ContextMenuTrigger asChild>
              {/* 行间去分割线（题库/文档表 08-31 同款纪律）：结构线只留表头
                 发丝线；hover 浅底 + cursor 承担可点暗示。 */}
              <TableRow
                className="group cursor-pointer border-0"
                data-testid={`eval-run-row-${run.run_id}`}
                onClick={() => onOpenRun(run.run_id)}
                onContextMenu={() => handleRowContextMenu(run.run_id)}
              >
                {/* 选题复选框（题库同款）：单元格 stopPropagation，勾选不开 drawer；
                    悬停/勾选/任一选中才显形。 */}
                <TableCell className="w-8 px-2 py-2" onClick={(event) => event.stopPropagation()}>
                  <Checkbox
                    aria-label={htk.rowSelectAria(formatRunTime(run.created_at))}
                    checked={isSelected}
                    className={`opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100 ${selectedIds.size > 0 ? "opacity-100" : ""}`}
                    onCheckedChange={(checked) => toggleRun(run.run_id, checked === true)}
                  />
                </TableCell>
                <TableCell className="px-2 py-2">{renderTimeCell(run)}</TableCell>
                <TableCell className="px-2 py-2">
                  {/* 胶囊盒体与列网格线齐线（八轮用户纠正）：-ml-2 退役——盒体
                      边缘才是对齐主体，芯片内边距是芯片自己的语言。 */}
                  <Badge variant="outline">
                    {envLabel(run)}
                  </Badge>
                </TableCell>
                <TableCell
                  className={
                    scopeLabel(run) === null
                      ? "text-muted-foreground px-2 py-2"
                      : "px-2 py-2"
                  }
                >
                  {scopeLabel(run) ?? "—"}
                </TableCell>
                <TableCell className="px-2 py-2">
                  <span className="flex items-center gap-1 text-sm">
                    {renderStatus(run)}
                  </span>
                </TableCell>
                {/* 时长列（八轮）：右对齐数值列，表头同右轴；muted xs tabular-nums。 */}
                <TableCell className="text-muted-foreground px-2 py-2 text-right text-xs tabular-nums">
                  {durationText(run) ?? "—"}
                </TableCell>
                {/* 末列悬浮三点（题库同款）：行级删除入口（不依赖选择态）；
                    hover/选中/聚焦/菜单开时淡入，静止态不抢戏。 */}
                <TableCell className="w-10 py-2 pr-4 pl-1 text-right" onClick={(event) => event.stopPropagation()}>
                  <div
                    className={`flex justify-end transition-opacity opacity-0 group-hover:opacity-100 focus-within:opacity-100 has-[[data-state=open]]:opacity-100 ${isSelected ? "opacity-100" : ""}`}
                    data-testid="history-row-more"
                  >
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button aria-label={rtk.moreActions} className="size-6" size="icon" variant="ghost">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-44">
                        <DropdownMenuItem variant="destructive" onSelect={() => setDeleteTargets([run.run_id])}>
                          <Trash2 className="size-4" />
                          {htk.rowDelete}
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
                      {/* 结构节奏同题库右键菜单：普通动作 → 取消选择（X）→
                          分隔线 → 危险操作沉底单独隔离。 */}
                      <ContextMenuItem onSelect={() => setSelectedIds(new Set())}>
                        <X className="size-4" />
                        {rtk.cancelSelection}
                      </ContextMenuItem>
                      <ContextMenuSeparator />
                      <ContextMenuItem
                        variant="destructive"
                        onSelect={() => runAfterMenuClose(() => setDeleteTargets([...selectedIds]))}
                      >
                        <Trash2 className="size-4" />
                        {rtk.deleteSelected}
                      </ContextMenuItem>
                    </>
                  ) : (
                    <>
                      {/* 单选：右键即选中；删除措辞两态对称（同题库）。 */}
                      <ContextMenuItem onSelect={() => setSelectedIds(new Set())}>
                        <X className="size-4" />
                        {rtk.cancelSelection}
                      </ContextMenuItem>
                      <ContextMenuSeparator />
                      <ContextMenuItem
                        variant="destructive"
                        onSelect={() => runAfterMenuClose(() => setDeleteTargets([run.run_id]))}
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
      ) : (
        <div className="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm">
          {htk.emptyHistory}
        </div>
      )}

      {/* 删除二次确认（题库同节奏）：单条展示运行时间+环境，批量展示已选计数；
          含基线行追加警示行（删后回退门禁失参照）。 */}
      <Dialog onOpenChange={(open) => !open && setDeleteTargets(null)} open={deleteTargets !== null}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{htk.deleteConfirmTitle}</DialogTitle>
            <DialogDescription>
              {deleteTargets?.length === 1 && targetRuns[0]
                ? `${formatRunTime(targetRuns[0].created_at)} · ${envLabel(targetRuns[0])}`
                : rtk.selectedCount(deleteTargets?.length ?? 0)}
              <br />
              {htk.deleteConfirmDesc(deleteTargets?.length ?? 0)}
              {targetsIncludeBaseline && (
                <>
                  <br />
                  {htk.baselineWarn}
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setDeleteTargets(null)} variant="outline">
              {qtk.deleteConfirm.cancel}
            </Button>
            <Button onClick={() => void handleDeleteConfirm()} variant="destructive">
              {qtk.deleteConfirm.confirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
