/**
 * Eval metrics overview component (spec 2026-08-24 §3.3/§3.4, plan Task 2).
 *
 * Props-driven shell: no built-in fetch — overview injected by the parent tab.
 * Color thresholds come from baseline_diff.threshold_percent (CI gate same origin),
 * never hard-coded. Null values render as dash with muted styling.
 */
"use client";

import { Dices, Info, Quote, Search, Sparkles } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import type { Layer1CategoryKey, MetricsOverview, TrendResponse } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { classifyRagasSkipReason, getProgressBarColor, getSummaryBandClass } from "./eval-metrics-overview.utils";
import { EvalSparkline } from "./eval-sparkline";

interface EvalMetricsOverviewProps {
  overview: MetricsOverview;
  onViewTrace?: (url: string) => void;
  /** 7 个 L2 瓦片的 sparkline 数据源（useEvalTrend 的 sparks，与粒度解耦）；
   *  trend query 未就绪时为 undefined，瓦片数值行保持原样（无迷你线）。 */
  sparks?: TrendResponse["sparks"];
}

/** Format value to percentage (1 decimal place) or return empty if null. */
const percent = (v: number | null): string => (v == null ? "" : `${(v * 100).toFixed(1)}%`);

export function EvalMetricsOverview({ overview, onViewTrace, sparks }: EvalMetricsOverviewProps) {
  const { t } = useI18n();
  const tk = t.knowledge.eval;
  const { layer1, layer2 } = overview;
  // 容器收起态（2026-09-05）：头部左簇 toggle 按钮整块点击收起/展开，
  // 与检索测试路容器同词汇（chevron 退役——整栏点击即收起，箭头视觉噪声）。
  const [layer1Collapsed, setLayer1Collapsed] = useState(false);
  const [layer2Collapsed, setLayer2Collapsed] = useState(false);

  return (
    // 两张等权 bg-card 容器卡（2026-09-05 容器化）：项目面板配方 bg-card +
    // border + shadow-xs + 卡内头部行（border-b）——与检索测试路容器/实体
    // 抽屉卡同词汇；Layer 2 两子组用实体抽屉同款分组头（小图标 + caption）。
    <div className="space-y-4">
      {/* Layer 1 表格 */}
      <section className="bg-card text-card-foreground overflow-hidden rounded-lg border shadow-xs">
        <div className={cn("flex items-center gap-2 px-4 py-2.5", !layer1Collapsed && "border-b")}>
          <button
            aria-expanded={!layer1Collapsed}
            className="hover:bg-muted/50 flex min-w-0 items-center gap-2 rounded-md px-2 py-0.5 text-left text-sm font-semibold transition-colors"
            data-testid="eval-layer1-toggle"
            type="button"
            onClick={() => setLayer1Collapsed((v) => !v)}
          >
            <Search className="text-muted-foreground size-3.5 shrink-0" />
            <span className="whitespace-nowrap shrink-0">{tk.layer1Title}</span>
          </button>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                data-testid="eval-layer1-info"
                aria-label={tk.layer1Note}
                className="inline-flex text-muted-foreground hover:text-foreground"
              >
                <Info className="size-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-60 whitespace-pre-wrap text-pretty">{tk.layer1Note}</TooltipContent>
          </Tooltip>
          {layer1?.baseline_diff?.regression_detected && (
            <Badge className="ml-auto shrink-0" variant="destructive">{tk.regressionBadge}</Badge>
          )}
        </div>
        {!layer1Collapsed && (
          /* 每卡独立横向滑块（2026-09-05）：min-w 下限沉进卡内——窄栏时表格
             自己横滚，不拖生成质量卡同滚（旧设计两卡共用总览块一个滑块）；
             顶边距 pt-2 + 表头 h-8：表头行与上下分割线不再疏离。 */
          <ScrollArea
            className="min-w-0"
            data-testid="eval-layer1-scroll"
            horizontal
            scrollHideDelay={2000}
            type="scroll"
          >
            <div className="min-w-[25rem] px-4 pt-2 pb-4">
              {layer1 ? (
                <Layer1Table metrics={layer1.metrics} />
              ) : (
                <EmptyHint text={tk.emptyLayer1} />
              )}
            </div>
          </ScrollArea>
        )}
      </section>

      {/* Layer 2 瓦片 */}
      <section className="bg-card text-card-foreground overflow-hidden rounded-lg border shadow-xs">
        <div className={cn("flex items-center gap-2 px-4 py-2.5", !layer2Collapsed && "border-b")}>
          <button
            aria-expanded={!layer2Collapsed}
            className="hover:bg-muted/50 flex min-w-0 items-center gap-2 rounded-md px-2 py-0.5 text-left text-sm font-semibold transition-colors"
            data-testid="eval-layer2-toggle"
            type="button"
            onClick={() => setLayer2Collapsed((v) => !v)}
          >
            <Sparkles className="text-muted-foreground size-3.5 shrink-0" />
            <span data-testid="eval-layer2-title" className="whitespace-nowrap shrink-0">{tk.layer2Title}</span>
          </button>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                data-testid="eval-layer2-info"
                aria-label={tk.layer2Note}
                className="inline-flex text-muted-foreground hover:text-foreground"
              >
                <Info className="size-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-60 text-pretty">{tk.layer2Note}</TooltipContent>
          </Tooltip>
          {layer2 && !layer2.ragas_available && (
            classifyRagasSkipReason(layer2.ragas_skip_reason) === "error" ? (
              <span className="ml-auto flex items-center gap-1 shrink-0">
                <Badge variant="secondary" data-testid="eval-ragas-badge">{tk.ragasErrorBadge}</Badge>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      data-testid="eval-ragas-error-info"
                      aria-label={layer2.ragas_skip_reason}
                      className="inline-flex text-muted-foreground hover:text-foreground"
                    >
                      <Info className="size-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-60 text-pretty whitespace-pre-wrap">{layer2.ragas_skip_reason}</TooltipContent>
                </Tooltip>
              </span>
            ) : (
              <Badge variant="secondary" className="ml-auto" data-testid="eval-ragas-badge">
                {tk.ragasMissingBadge}
              </Badge>
            )
          )}
        </div>
        {!layer2Collapsed &&
          (layer2 ? (
            <ScrollArea
              className="min-w-0"
              data-testid="eval-layer2-scroll"
              horizontal
              scrollHideDelay={2000}
              type="scroll"
            >
              <div className="@container min-w-[27rem] space-y-4 p-4">
              <div>
              <div className="text-muted-foreground mb-2 flex items-center gap-1.5 text-xs font-medium">
                <Dices className="size-3.5" />
                {tk.ragasGroupLabel}
              </div>
              {/* 固定列数：宽度下限为本卡自有 min-w-[27rem]（触底时仅本卡横滚；
                  下限按数值固有宽重算——触底瓦片内宽 ≈67 ≥ 最坏 "100.0%" ≈65，
                  2026-09-07 溢出治理）。窄档隐线走本卡体 @container 容器查询降档。 */}
              <div className="grid grid-cols-4 gap-3">
                <MetricTile title={tk.ragasCard.faithfulness} note={tk.cardNote.faithfulness} value={layer2.ragas.faithfulness} traceUrl={layer2.langfuse_trace_url} onViewTrace={onViewTrace} traceLabel={tk.viewTrace} spark={sparks?.faithfulness} testId="faithfulness" />
                <MetricTile title={tk.ragasCard.answerRelevancy} note={tk.cardNote.answerRelevancy} value={layer2.ragas.answer_relevancy} spark={sparks?.answer_relevancy} testId="answer_relevancy" />
                <MetricTile title={tk.ragasCard.contextPrecision} note={tk.cardNote.contextPrecision} value={layer2.ragas.context_precision} spark={sparks?.context_precision} testId="context_precision" />
                <MetricTile title={tk.ragasCard.contextRecall} note={tk.cardNote.contextRecall} value={layer2.ragas.context_recall} spark={sparks?.context_recall} testId="context_recall" />
              </div>
            </div>
            <div>
              <div className="text-muted-foreground mb-2 flex items-center gap-1.5 text-xs font-medium">
                <Quote className="size-3.5" />
                {tk.archGroupLabel}
              </div>
              {/* 统一 grid-cols-4（2026-09-05）：引用组原 3 瓦片留一空槽——
                  纵向列轴与 RAGAS 组对齐；空槽由路由命中率瓦片填满
                  （2026-09-08 总览露出，layer2 顶层 path_accuracy 换展示面键名）。 */}
              <div className="grid grid-cols-4 gap-3">
                <MetricTile title={tk.citationPrecision} note={tk.cardNote.citationPrecision} value={layer2.arch_specific.citation_precision} spark={sparks?.citation_precision} testId="citation_precision" />
                <MetricTile title={tk.citationRecall} note={tk.cardNote.citationRecall} value={layer2.arch_specific.citation_recall} spark={sparks?.citation_recall} testId="citation_recall" />
                <MetricTile
                  title={tk.seedHitRate}
                  note={tk.cardNote.seedHitRate}
                  value={layer2.arch_specific.seed_hit_rate}
                  disabled={!layer2.has_graph_questions}
                  disabledReason={tk.noGraphQuestions}
                  spark={sparks?.seed_hit_rate}
                  testId="seed_hit_rate"
                />
                <MetricTile
                  title={tk.routingHitRate}
                  note={tk.cardNote.routingHitRate}
                  value={layer2.routing_hit_rate}
                  spark={sparks?.routing_hit_rate}
                  testId="routing_hit_rate"
                />
              </div>
              </div>
              </div>
            </ScrollArea>
          ) : (
            <div className="p-4">
              <EmptyHint text={tk.emptyLayer2} />
            </div>
          ))}
      </section>
    </div>
  );
}

function Layer1Table({ metrics }: { metrics: NonNullable<MetricsOverview["layer1"]>["metrics"] }) {
  const { t } = useI18n();
  const tk = t.knowledge.eval;
  // Category order matches wire keys; categories missing from by_category are skipped.
  // 钉 Layer1CategoryKey（2026-09-07）：keyof metrics 会含 questions/top_k 新键，
  // 索引联合进 EvalQuestionMetric[] 破坏分类行类型。
  const categories: Array<Layer1CategoryKey | "summary"> = ["fact", "relation", "concept", "global", "summary"];

  return (
    /* 表格外壳不走默认 overflow-x-auto（老原生滑块）：横滚由卡内 ScrollArea
       的 overlay 细滑块承担（2026-09-04 统一设计，题库表同款 containerClassName）。 */
    <Table containerClassName="relative w-full" data-testid="eval-layer1-table">
      <TableHeader>
        <TableRow>
          {/* 列宽平摊（2026-09-05 二轮纠正）：表格 w-full 自然平摊——列距随栏宽
              伸缩（窄栏自然聚拢），固定列宽等于给每列设下限、退役；行高紧凑档
              （head h-8 / cell py-1.5）+ 卡体顶边距 pt-2：表头行与分割线贴齐。 */}
          <TableHead className="h-8 px-2">{tk.tableCategory}</TableHead>
          {/* 数值列表头右对齐（2026-08-30）：与数据同轴，主流规范文本左/数值右 */}
          <TableHead className="h-8 px-2 text-right">{tk.tableHitRate}</TableHead>
          <TableHead className="h-8 px-2 text-right">{tk.tableRecallAtK(metrics.top_k ?? null)}</TableHead>
          <TableHead className="h-8 px-2 text-right">{tk.tableMrr}</TableHead>
          <TableHead className="h-8 px-2 text-right">{tk.tablePathAccuracy}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {categories.map((category, _) => {
          const metric =
            category === "summary" ? metrics.summary : metrics[category] ?? null;
          const hasData = !!metric;
          const isSummary = category === "summary";
          const testId = isSummary ? "eval-row-summary" : `eval-row-${category}`;

          // Muted row for missing category (category not present in this batch).
          if (!hasData) {
            return (
              <TableRow key={category} data-testid={testId} className="text-muted-foreground">
                {/* 题量后缀与数据行同词汇（2026-09-06 对齐）：缺失类显 (n=0) 而非
                    长解释句——注释列全表统一「名称 (n=K)」，纵向一眼可比。 */}
                <TableCell className="py-1.5" colSpan={5}>
                  {tk.category[category]}{" "}
                  <span className="font-normal">(n=0)</span>
                </TableCell>
              </TableRow>
            );
          }

          // Summary row styled with border-top + 底色区分（2026-09-05 容器化：
          // 卡内 muted 是正确的前进层级，汇总行一眼可辨）。
          const summaryRowClassName = isSummary ? "border-t-2 bg-muted/40 font-semibold" : undefined;

          return (
            <TableRow key={category} data-testid={testId} className={summaryRowClassName}>
              <TableCell className="py-1.5">
                {/* 题量后缀全行统一（2026-09-05）：summary 的 question_count 即 wire
                    给的全题口径（n=总题数），与分类行同词汇同 muted 样式。 */}
                {tk.category[category]}{" "}
                <span className="text-muted-foreground font-normal">(n={metric.question_count})</span>
              </TableCell>
            {/* 数值单元格右对齐 + tabular-nums（2026-08-30）：% 纵向成列。
                汇总行（2026-09-05）：数值改胶囊（90/80 三档），颜色收进胶囊；
                分类行全中性（2026-09-06）：delta/绝对裸色退役，回归信号归卡头
                徽章 + 趋势图——全表仅汇总胶囊带色，焦点唯一。 */}
              <TableCell className={cn(isSummary ? "py-1" : "py-1.5", "text-right tabular-nums")} data-testid={`eval-cell-hit-${category}`}>{isSummary ? <SummaryCapsule value={metric.hit_rate} /> : percent(metric.hit_rate)}</TableCell>
              <TableCell className={cn(isSummary ? "py-1" : "py-1.5", "text-right tabular-nums")} data-testid={`eval-cell-recall-${category}`}>{isSummary ? <SummaryCapsule value={metric.recall_at_k} /> : percent(metric.recall_at_k)}</TableCell>
              {/* 数值语言统一（2026-09-05）：MRR 同走百分数——产品重心（瓦片/阈值
                  芯片/趋势轴）全在 %，IR 味三位小数退役。 */}
              <TableCell className={cn(isSummary ? "py-1" : "py-1.5", "text-right tabular-nums")} data-testid={`eval-cell-mrr-${category}`}>{isSummary ? <SummaryCapsule value={metric.mrr} /> : percent(metric.mrr)}</TableCell>
              <TableCell className={cn(isSummary ? "py-1" : "py-1.5", "text-right tabular-nums")} data-testid={`eval-cell-path-${category}`}>{isSummary ? <SummaryCapsule value={metric.path_accuracy} /> : percent(metric.path_accuracy)}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** 汇总行数值胶囊（2026-09-05）：检索测试延时芯片同款胶囊/同色 trio，按绝对值
    三档（≥0.9 emerald / ≥0.8 lime / <0.8 orange）。汇总行颜色收进胶囊、行文字
    不着裸色；数字保持表格字号（头牌不缩成芯片 10px）。null 显破折号无胶囊。 */
function SummaryCapsule({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground">-</span>;
  return (
    /* -mr-1.5 抵消胶囊右内边距（2026-09-06 对齐）：数字右缘与分类行/表头同列，
       否则 px-1.5 会把汇总数字往左推 6px 造成纵列错位。 */
    <span className={cn("-mr-1.5 inline-flex items-center rounded-md px-1.5 py-0.5 tabular-nums", getSummaryBandClass(value))}>
      {percent(value)}
    </span>
  );
}

/** Per-card ⓘ tooltip: full name + one-line explanation live here, title stays short. */
function MetricNote({ note, testId }: { note: string; testId: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          data-testid={testId}
          aria-label={note}
          className="inline-flex shrink-0 text-muted-foreground hover:text-foreground"
        >
          <Info className="size-3.5" />
        </button>
      </TooltipTrigger>
      {/* max-w-60 + text-pretty：基类 text-balance 会把每行均衡缩短、盒子却被 max-w 顶满，
          右侧留出大片空白；pretty 换行让文字填满盒子。 */}
      <TooltipContent className="max-w-60 text-pretty">{note}</TooltipContent>
    </Tooltip>
  );
}

/** 指标瓦片（2026-09-05 容器化）：白卡内 bg-muted/40 内凹小卡（正确嵌套
    层级——外层已抬升，内层用后退色分组）；内容 = 名称+ⓘ / 大数字 / h-1
    进度条。trace 链接挂名称行右端（faithfulness 专属，testId 哨兵不变）。
    null 显破折号且无进度条；disabled 加透明度 + 原因行。 */
function MetricTile({ title, note, value, disabled, disabledReason, traceUrl, onViewTrace, traceLabel, spark, testId }: { title: string; note: string; value: number | null; disabled?: boolean; disabledReason?: string; traceUrl?: string; onViewTrace?: (url: string) => void; traceLabel?: string; spark?: number[]; testId: string }) {
  const colorClass = getProgressBarColor(value);
  const isNull = value == null;
  return (
    <div
      className={cn("bg-muted/40 rounded-lg px-3 py-2.5", (disabled === true || isNull) && "opacity-60")}
      data-testid={`eval-card-${testId}`}
    >
      <div className="text-muted-foreground flex items-center gap-1 text-xs">
        <span className="min-w-0 truncate" data-testid={`eval-card-title-${testId}`}>{title}</span>
        <MetricNote note={note} testId={`eval-card-note-${testId}`} />
        {testId === "faithfulness" && traceUrl && traceLabel && onViewTrace && (
          <button
            className="ml-auto shrink-0 underline-offset-2 hover:underline"
            type="button"
            onClick={() => onViewTrace(traceUrl)}
          >
            {traceLabel}
          </button>
        )}
      </div>
      {/* 数值行（2026-09-07 sparkline 接入）：数字左、迷你线右同行（28×12 =
          w-7 h-3），justify-between + gap-1；无 spark（缺键/空/单点）时
          EvalSparkline 返 null，数值行保持原样。窄栏溢出治理（2026-09-07）：
          数值行固有最小宽（值 ≈52–65 + gap 4 + 线 28）超窄档瓦片内宽，按信息
          优先级降档——sparkline 是扫描层装饰先隐：hidden + @min-[35rem]
          容器查询（卡体为 @container），仅容器 ≥35rem（瓦片内宽 ≥ 值+gap+28）
          时同行出现，以下档数值行只留数值。text-lg 恒原字号：主信息不缩不换。 */}
      <div className="mt-1 flex items-center justify-between gap-1" data-testid={`eval-card-value-${testId}`}>
        <div className="text-lg font-semibold tabular-nums">{isNull ? "-" : percent(value)}</div>
        <EvalSparkline values={spark} className="hidden @min-[35rem]:block" />
      </div>
      {!isNull && <Progress value={value * 100} className={cn("mt-1.5 h-1", colorClass)} />}
      {disabled && disabledReason && <div className="text-muted-foreground mt-1 text-xs">{disabledReason}</div>}
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}
