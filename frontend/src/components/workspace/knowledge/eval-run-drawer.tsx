"use client";

/**
 * 单次评测运行详情 drawer 壳（2026-08-24 spec §5，plan Task 6；2026-09-08
 * 容器化 + 裸奔退役重设计）：趋势图数据点 / 历史行点击下钻。只读摘要：
 * sticky 身份头（运行时间 mono 标题承载身份 + 环境/状态/评测内容/基线/回退
 * 芯片行，泛称沉 sr-only）+ 三张 bg-card 卡（运行信息：run_id 代码底 + 复制 /
 * 完整时间；检索质量 / 生成质量：两列内凹瓦片 + 三色进度条）。Layer 2 的
 * path_accuracy（真实对话链路选路准确率）与 Layer 1 同名指标口径不同，卡内
 * callout 标注——spec §5 冻结契约。
 * 容器配方沿用 eval-question-drawer（09-08 裸奔退役定案：bg-card + border +
 * rounded-lg + shadow-xs + 卡内分组头带 border-b）；瓦片词汇与总览 MetricTile
 * 同源（bg-muted/40 内凹 / text-lg 大数字 / h-1 进度条三色）；胶囊色族与历史
 * 表同源（基线=琥珀 / 回退=红）。逐题明细 UI 另立 spec。层未执行（*_metrics
 * 为 {}）渲染「未执行」提示。对齐 ChunkDrawer 的 Sheet 模式；不跳路由。
 */
import {
  Activity,
  Ban,
  CheckCircle2,
  Copy,
  Hash,
  Info,
  Search,
  SkipForward,
  Sparkles,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
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
import { useI18n } from "@/core/i18n/hooks";
import { formatKnowledgeTimestamp } from "@/core/knowledge/format";
import { useEvalRun } from "@/core/knowledge/hooks";
import type {
  EvalRunDetail,
  Layer1Metrics,
  RagasMetrics,
} from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { getProgressBarColor } from "./eval-metrics-overview.utils";
import { formatRunTime } from "./eval-run-history";
import { toast } from "./kb-toast";

/** 卡容器（eval-question-drawer 09-08 定案配方）：米色画布上 bg-card 抬升 +
    卡内分组头带 border-b；计数徽章 ml-auto。 */
const CARD = "bg-card text-card-foreground rounded-lg border shadow-xs";
const CARD_HEAD =
  "text-muted-foreground flex items-center gap-1.5 border-b px-3 py-2 text-xs font-medium";

/** 头部胶囊色族（历史表 09-08 三轮用户定案）：基线=琥珀、回退=红——检索测试
    耗时胶囊同族（bg-x-500/10 text-x-700 dark 提亮），同列兄弟胶囊同形同透明度。 */
const BASELINE_TONE = "bg-amber-500/10 text-amber-700 dark:text-amber-300";
const REGRESSION_TONE = "bg-red-500/10 text-red-700 dark:text-red-300";

/** 数值语言统一（2026-09-05）：全指标百分数 1 位小数，与总览表/瓦片/趋势轴
 *  同口径；MRR/RAGAS 三位小数口径退役。null 显破折号。 */
const percent = (v: number | null): string =>
  v == null ? "-" : `${(v * 100).toFixed(1)}%`;

function isLayer1Metrics(
  m: EvalRunDetail["layer1_metrics"],
): m is Layer1Metrics {
  return "summary" in m;
}

function isLayer2Metrics(
  m: EvalRunDetail["layer2_metrics"],
): m is Extract<EvalRunDetail["layer2_metrics"], { ragas: RagasMetrics }> {
  return "ragas" in m;
}

/** 状态图标（历史表 renderStatus 同词汇源）：error 红 / skipped·cancelled
    muted / completed 默认色；Badge 自带 [&>svg]:size-3 与 gap-1。 */
function RunStatusIcon({ status }: { status: EvalRunDetail["status"] }) {
  if (status === "error") return <XCircle aria-hidden />;
  if (status === "skipped") return <SkipForward aria-hidden />;
  if (status === "cancelled") return <Ban aria-hidden />;
  return <CheckCircle2 aria-hidden />;
}

export function EvalRunDrawer({
  kbId,
  runId,
  open,
  onOpenChange,
}: {
  kbId: string;
  runId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t, locale } = useI18n();
  const te = t.knowledge.eval;
  const td = te.drawer;
  const th = te.history;
  // 关闭态不残留请求：runId 置 null 即禁用查询（useEvalRun 门控）。
  const query = useEvalRun(kbId, open ? runId : null);
  const run = query.data;

  // 头部芯片行词汇（历史表同源）：环境 wire 键 → 本地化短词；评测内容按实际
  // 执行的两层指标推导，双层未跑不显（诚实缺省不假报内容）。
  const envLabel = run
    ? run.environment === "ci"
      ? th.envCi
      : run.environment === "nightly"
        ? th.envNightly
        : th.envLocal
    : "";
  const statusLabel = run
    ? run.status === "error"
      ? td.statusError
      : run.status === "skipped"
        ? td.statusSkipped
        : run.status === "cancelled"
          ? td.statusCancelled
          : td.statusCompleted
    : "";
  const scopeLabel = run
    ? isLayer1Metrics(run.layer1_metrics) && isLayer2Metrics(run.layer2_metrics)
      ? th.scopeFull
      : isLayer1Metrics(run.layer1_metrics)
        ? th.scopeQuick
        : isLayer2Metrics(run.layer2_metrics)
          ? th.scopeGeneration
          : null
    : null;

  if (!runId) return null;

  // 复制 run_id（settings 集成页同款）：成功/失败 toast 走 clipboard 现成词汇。
  const copyRunId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
      toast.success(t.clipboard.copiedToClipboard);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  };

  return (
    <Sheet onOpenChange={onOpenChange} open={open}>
      <SheetContent className="w-full overflow-hidden sm:max-w-xl" side="right">
        {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：整抽屉经 ScrollArea 滚动
            （type="scroll"、停 2s 淡出、不占宽），取代 SheetContent 原生 overflow-y-auto；
            × 关闭钮由随内容滚改为钉住。 */}
        <ScrollArea
          className="min-h-0 flex-1"
          scrollHideDelay={2000}
          type="scroll"
        >
          {/* sticky 身份头（eval-question-drawer 09-08 同款）：运行时间 mono 标题
              承载身份，泛称沉 sr-only 描述；芯片行随头不随滚。loading/error 态
              回退泛称标题。 */}
          <SheetHeader className="sticky top-0 z-10 border-b bg-background/95 px-4 py-2.5 backdrop-blur-sm">
            {run ? (
              <>
                <div className="flex min-w-0 items-start gap-1.5 pr-8">
                  <Activity className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                  <div className="min-w-0">
                    <SheetTitle
                      className="font-mono text-sm tabular-nums"
                      data-testid="eval-drawer-title"
                    >
                      {formatRunTime(run.created_at)}
                    </SheetTitle>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{envLabel}</Badge>
                      <Badge variant="secondary">
                        <RunStatusIcon status={run.status} />
                        {statusLabel}
                      </Badge>
                      {scopeLabel && (
                        <Badge variant="secondary">{scopeLabel}</Badge>
                      )}
                      {run.is_baseline && (
                        <span
                          className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${BASELINE_TONE}`}
                        >
                          {td.baselineBadge}
                        </span>
                      )}
                      {run.baseline_diff?.regression_detected && (
                        <span
                          className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${REGRESSION_TONE}`}
                        >
                          {te.regressionBadge}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <SheetDescription className="sr-only">
                  {td.title}
                </SheetDescription>
              </>
            ) : (
              <SheetTitle>{td.title}</SheetTitle>
            )}
          </SheetHeader>
          <div className="flex flex-col gap-3 px-4 py-3">
            {query.isLoading && (
              <p className="text-muted-foreground py-4 text-center text-sm">
                {te.loading}
              </p>
            )}
            {query.error && (
              <p className="text-destructive py-4 text-center text-sm">
                {te.loadFailed}
              </p>
            )}
            {run && (
              <>
                {/* 运行信息卡：run_id 代码底 + 复制钮退役裸奔；完整时间直显
                    （退役 toLocaleString，formatKnowledgeTimestamp 同历史表 tooltip 源）。 */}
                <section className={CARD}>
                  <header className={CARD_HEAD}>
                    <Hash className="size-3.5" />
                    {td.runInfoSection}
                  </header>
                  <div className="grid grid-cols-[3.5rem_1fr] gap-x-3 gap-y-2 p-3 text-sm">
                    <span className="text-muted-foreground text-xs">
                      {td.runIdLabel}
                    </span>
                    <span className="flex min-w-0 items-start gap-1.5">
                      <span className="bg-muted/40 min-w-0 flex-1 rounded-md px-2 py-1 font-mono text-xs break-all">
                        {run.run_id}
                      </span>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            aria-label={t.clipboard.copyToClipboard}
                            className="size-6 shrink-0"
                            data-testid="eval-drawer-copy-run-id"
                            onClick={() => void copyRunId(run.run_id)}
                            size="icon"
                            type="button"
                            variant="ghost"
                          >
                            <Copy className="size-3.5" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-60 text-pretty">
                          {t.clipboard.copyToClipboard}
                        </TooltipContent>
                      </Tooltip>
                    </span>
                    <span className="text-muted-foreground text-xs">
                      {td.createdAtLabel}
                    </span>
                    <span
                      className="font-mono text-xs tabular-nums"
                      data-testid="eval-drawer-created-at"
                    >
                      {formatKnowledgeTimestamp(run.created_at, locale)}
                    </span>
                  </div>
                </section>

                {/* 检索质量卡：summary 摘要级四瓦片（L1 无 ⓘ——总览同无 note 词汇）；
                    题量计数徽章 ml-auto（总览 (n=K) 同词汇）。 */}
                <section className={CARD}>
                  <header className={CARD_HEAD}>
                    <Search className="size-3.5" />
                    {td.layer1Section}
                    {isLayer1Metrics(run.layer1_metrics) && (
                      <Badge
                        className="ml-auto px-1.5 text-[10px]"
                        variant="secondary"
                      >
                        {`n=${run.layer1_metrics.summary.question_count}`}
                      </Badge>
                    )}
                  </header>
                  <div className="p-3">
                    {isLayer1Metrics(run.layer1_metrics) ? (
                      <div className="grid grid-cols-2 gap-2">
                        <DrawerMetricTile
                          label={te.tableHitRate}
                          value={run.layer1_metrics.summary.hit_rate}
                          testId="hit_rate"
                        />
                        <DrawerMetricTile
                          label={te.tableRecallAtK(
                            run.layer1_metrics.top_k ?? null,
                          )}
                          value={run.layer1_metrics.summary.recall_at_k}
                          testId="recall_at_k"
                        />
                        <DrawerMetricTile
                          label={te.tableMrr}
                          value={run.layer1_metrics.summary.mrr}
                          testId="mrr"
                        />
                        <DrawerMetricTile
                          label={te.tablePathAccuracy}
                          value={run.layer1_metrics.summary.path_accuracy}
                          testId="path_accuracy"
                        />
                      </div>
                    ) : (
                      <NotRunHint text={td.notRun} />
                    )}
                  </div>
                </section>

                {/* 生成质量卡：八瓦片（ragas 4 + 引用 3 带 ⓘ = cardNote 现成词汇；
                    seed 无 graph 题 disabled + 原因行）；path_accuracy 口径 callout
                    （spec §5 冻结契约可见——裸段落退役为卡内带图标 callout）。 */}
                <section className={CARD}>
                  <header className={CARD_HEAD}>
                    <Sparkles className="size-3.5" />
                    {td.layer2Section}
                  </header>
                  <div className="p-3">
                    {isLayer2Metrics(run.layer2_metrics) ? (
                      <>
                        <div className="grid grid-cols-2 gap-2">
                          <DrawerMetricTile
                            label={te.trend.faithfulness}
                            note={te.cardNote.faithfulness}
                            value={run.layer2_metrics.ragas.faithfulness}
                            testId="faithfulness"
                          />
                          <DrawerMetricTile
                            label={te.trend.answerRelevancy}
                            note={te.cardNote.answerRelevancy}
                            value={run.layer2_metrics.ragas.answer_relevancy}
                            testId="answer_relevancy"
                          />
                          <DrawerMetricTile
                            label={te.trend.contextPrecision}
                            note={te.cardNote.contextPrecision}
                            value={run.layer2_metrics.ragas.context_precision}
                            testId="context_precision"
                          />
                          <DrawerMetricTile
                            label={td.contextRecallLabel}
                            note={te.cardNote.contextRecall}
                            value={run.layer2_metrics.ragas.context_recall}
                            testId="context_recall"
                          />
                          <DrawerMetricTile
                            label={te.citationPrecision}
                            note={te.cardNote.citationPrecision}
                            value={
                              run.layer2_metrics.arch_specific
                                .citation_precision
                            }
                            testId="citation_precision"
                          />
                          <DrawerMetricTile
                            label={te.citationRecall}
                            note={te.cardNote.citationRecall}
                            value={
                              run.layer2_metrics.arch_specific.citation_recall
                            }
                            testId="citation_recall"
                          />
                          <DrawerMetricTile
                            disabled={!run.layer2_metrics.has_graph_questions}
                            disabledReason={te.noGraphQuestions}
                            label={te.seedHitRate}
                            note={te.cardNote.seedHitRate}
                            value={
                              run.layer2_metrics.arch_specific.seed_hit_rate
                            }
                            testId="seed_hit_rate"
                          />
                          <DrawerMetricTile
                            label={te.routingHitRate}
                            value={run.layer2_metrics.path_accuracy ?? null}
                            testId="routing_hit_rate"
                          />
                        </div>
                        {/* 口径 callout（spec §5 冻结契约可见）：复用 cardNote 单一
                            词汇源（总览瓦片 ⓘ 同款文案），裸段落退役为带图标 callout。 */}
                        <p className="text-muted-foreground mt-2 flex items-start gap-1.5 text-xs">
                          <Info className="mt-0.5 size-3.5 shrink-0" />
                          {te.cardNote.routingHitRate}
                        </p>
                      </>
                    ) : (
                      <NotRunHint text={td.notRun} />
                    )}
                  </div>
                </section>
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}

/** 内凹瓦片（总览 MetricTile 同词汇降档两列）：白卡内 bg-muted/40 内凹小卡 =
    正确嵌套层级；名称+ⓘ / text-lg 大数字 / h-1 三色进度条（getProgressBarColor
    同源自总览 utils）；null/disabled = opacity-60 + 破折号无进度条。 */
function DrawerMetricTile({
  label,
  note,
  value,
  disabled,
  disabledReason,
  testId,
}: {
  label: string;
  note?: string;
  value: number | null;
  disabled?: boolean;
  disabledReason?: string;
  testId: string;
}) {
  const isNull = value == null;
  return (
    <div
      className={cn(
        "bg-muted/40 rounded-lg px-3 py-2.5",
        (disabled === true || isNull) && "opacity-60",
      )}
      data-testid={`eval-drawer-tile-${testId}`}
    >
      <div className="text-muted-foreground flex items-center gap-1 text-xs">
        <span className="min-w-0 truncate">{label}</span>
        {note && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                aria-label={note}
                className="text-muted-foreground hover:text-foreground inline-flex shrink-0"
                data-testid={`eval-drawer-tile-note-${testId}`}
                type="button"
              >
                <Info className="size-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-60 text-pretty">
              {note}
            </TooltipContent>
          </Tooltip>
        )}
      </div>
      <div
        className="mt-1 text-lg font-semibold tabular-nums"
        data-testid={`eval-drawer-tile-value-${testId}`}
      >
        {isNull ? "-" : percent(value)}
      </div>
      {!isNull && (
        <Progress
          className={cn("mt-1.5 h-1", getProgressBarColor(value))}
          value={value * 100}
        />
      )}
      {disabled === true && disabledReason && (
        <div className="text-muted-foreground mt-1 text-xs">
          {disabledReason}
        </div>
      )}
    </div>
  );
}

/** 层未执行提示（卡内 dashed 占位，总览 EmptyHint 同词汇降档）。 */
function NotRunHint({ text }: { text: string }) {
  return (
    <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-center text-xs">
      {text}
    </p>
  );
}
