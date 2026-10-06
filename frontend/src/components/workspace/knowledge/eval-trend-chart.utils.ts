/**
 * 评测趋势图 option 组装纯函数（2026-08-24 spec §4.3/§4.6，plan Task 3）。
 * 不 import echarts 运行时，只用类型（对齐 graph-utils.ts 先例）——jsdom 可直测。
 *
 * 冻结取舍（spec §4.1）：趋势图只上 6 条线——Layer 1 三指标（实线 = 确定性、
 * 进 CI 门禁）+ RAGAS 三指标（虚线 = 概率性、只报告）；context_recall 与
 * context_precision 同族同向故省略，架构专属指标入口在总览卡片与 drawer。
 */
import type { LineSeriesOption } from "echarts/charts";
import type { EChartsCoreOption } from "echarts/core";

import type { TrendChartLabels, TrendPoint, TrendResponse } from "@/core/knowledge/types";

/** 指标线定义表（颜色/线型/默认显隐按 spec §4.3.2 冻结，实施时不得变更）。 */

/** 滑条缩放的最少点数（2026-09-05）：点数稀疏时常驻滑条纯噪声，退役。 */
const DATA_ZOOM_MIN_POINTS = 8;
interface MetricDef {
  key:
    | "recall_at_k"
    | "hit_rate"
    | "mrr"
    | "faithfulness"
    | "answer_relevancy"
    | "context_precision";
  labelKey:
    | "recallAtK"
    | "hitRate"
    | "mrr"
    | "faithfulness"
    | "answerRelevancy"
    | "contextPrecision";
  color: string;
  /** Layer 1 = 实线实心圆（硬约束）；Layer 2 = 虚线空心圆（judge 方差，参考）。 */
  layer: 1 | 2;
  /** 默认只显示 Recall@k + Hit Rate，其余经图例点击开启（防拥挤）。 */
  defaultOn: boolean;
}

const METRICS: readonly MetricDef[] = [
  { key: "recall_at_k", labelKey: "recallAtK", color: "#3B82F6", layer: 1, defaultOn: true },
  { key: "hit_rate", labelKey: "hitRate", color: "#10B981", layer: 1, defaultOn: true },
  { key: "mrr", labelKey: "mrr", color: "#8B5CF6", layer: 1, defaultOn: false },
  { key: "faithfulness", labelKey: "faithfulness", color: "#F59E0B", layer: 2, defaultOn: false },
  { key: "answer_relevancy", labelKey: "answerRelevancy", color: "#EC4899", layer: 2, defaultOn: false },
  { key: "context_precision", labelKey: "contextPrecision", color: "#06B6D4", layer: 2, defaultOn: false },
];

/** 趋势图可画的 11 个数值指标键（6 图例 + 5 picker），均为 TrendPoint 的可空数值键。 */
export type TrendMetricKey =
  | "recall_at_k"
  | "hit_rate"
  | "mrr"
  | "path_accuracy"
  | "faithfulness"
  | "answer_relevancy"
  | "context_precision"
  | "citation_precision"
  | "citation_recall"
  | "seed_hit_rate"
  | "routing_hit_rate";

/** picker 稀疏指标线定义（spec §4.3）：5 个仅完整档产出的候选，线型沿用 layer 语义。 */
export interface PickerMetricDef {
  key: "path_accuracy" | "citation_precision" | "citation_recall" | "seed_hit_rate" | "routing_hit_rate";
  labelKey: "pathAccuracy" | "citationPrecision" | "citationRecall" | "seedHitRate" | "routingHitRate";
  color: string;
  /** Layer 1 = 实线实心圆；Layer 2 = 虚线空心圆（与图例六线同语义）。 */
  layer: 1 | 2;
}

/** picker 5 候选（颜色冻结，与图例六色不撞；spec §4.3 + plan Global Constraints；
    路由命中率 slate 中性色——与十色均不同相，虚线空心圆承载 L2 语义）。 */
export const PICKER_METRICS: readonly PickerMetricDef[] = [
  { key: "path_accuracy", labelKey: "pathAccuracy", color: "#84CC16", layer: 1 },
  { key: "citation_precision", labelKey: "citationPrecision", color: "#F97316", layer: 2 },
  { key: "citation_recall", labelKey: "citationRecall", color: "#14B8A6", layer: 2 },
  { key: "seed_hit_rate", labelKey: "seedHitRate", color: "#A855F7", layer: 2 },
  { key: "routing_hit_rate", labelKey: "routingHitRate", color: "#64748B", layer: 2 },
];

/** 回退点标红色（regression.detected 驱动，per-category 门禁口径，§4.3.4）。 */
const REGRESSION_COLOR = "#EF4444";

/** datum 携带 runId 与 metricKey——click/tooltip 从 data 取数，不依赖 dataIndex。 */
export interface TrendDatum {
  /** [run 序号索引, warp 后图高]——序号轴坐标（contract v5）。 */
  value: [number, number];
  /** 指标真值（0–1）：tooltip/环比一律报真值，不报 warp 值。 */
  raw: number;
  runId: string | null;
  metricKey: TrendMetricKey;
  /** 回退点项级覆写（仅 Recall@k 线）。 */
  itemStyle?: { color: string };
}

export interface TrendTooltipParam {
  seriesName?: string;
  color?: string;
  data?: TrendDatum;
}

/** 墨色：浅色主题用深灰，暗色主题翻成亮灰（vector-canvas ink() 先例）。 */
function ink(alpha: number, dark: boolean): string {
  return dark ? `rgba(235,238,245,${alpha})` : `rgba(60,60,60,${alpha})`;
}

export function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/** 数值语言统一（2026-09-05）：全指标百分数 1 位小数——与总览表/瓦片/阈值
 *  芯片同口径；MRR/RAGAS 三位小数退役（PERCENT_KEYS 白名单随之退役）。 */
function formatValue(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** 视窗预设（contract v4，spec 2026-09-07 §3）：日/周/月 = 客户端视窗
 *  24h/7d/30d——切档只移 dataZoom 窗口，不触发请求（服务端一次给 90d）。 */
export type SpanPreset = "day" | "week" | "month";

/** 预设点击请求（nonce 区分同档重复点击；eval-tab 持有，identity 变化才apply）。 */
export interface SpanRequest {
  preset: SpanPreset;
  nonce: number;
}

const SPAN_PRESET_MS: Record<SpanPreset, number> = {
  day: 24 * 3_600_000,
  week: 7 * 24 * 3_600_000,
  month: 30 * 24 * 3_600_000,
};

export function presetToSpanMs(preset: SpanPreset): number {
  return SPAN_PRESET_MS[preset];
}

/** 滚轮缩放可见跨度回算档位（按钮密度指示器）：≤36h=day / ≤14d=week / 其余=month。 */
export function spanToPreset(spanMs: number): SpanPreset {
  if (spanMs <= 36 * 3_600_000) return "day";
  if (spanMs <= 14 * 24 * 3_600_000) return "week";
  return "month";
}

/** 缩放密度档（contract v4）：可见 run ≤80 出符号点（放大看每次测试点），
 *  >80 隐符号只留线（缩小看总体趋势）——隐符号不降采样，hover 的 axis
 *  snap 仍命中真实 run。 */
export const SYMBOL_DENSITY_MAX = 80;

export function resolveShowSymbol(visibleCount: number): boolean {
  return visibleCount <= SYMBOL_DENSITY_MAX;
}

/** tooltip 头：命中 run 的本地 MM-DD HH:mm（contract v4：run 级点带时刻）。 */
export function formatPointTime(ts: string): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 分段加权纵轴（contract v5）冻结折点表（真值 → 图高）：权重 0–40 → 20%、
 *  40–80 → 20%、80–100 → 60%（其中 90–95 / 95–100 再各占 20% 二次放大）——
 *  默认六等分刻度恰落六个整值真值。 */
const WARP_STOPS: readonly (readonly [number, number])[] = [
  [0, 0],
  [0.4, 0.2],
  [0.8, 0.4],
  [0.9, 0.6],
  [0.95, 0.8],
  [1, 1],
];

/** 正向分段线性映射（真值比例 → 图高）；入参 clamp [0,1]。 */
export function warpValue(value: number): number {
  const v = Math.min(1, Math.max(0, value));
  for (let i = 1; i < WARP_STOPS.length; i += 1) {
    const [x0, y0] = WARP_STOPS[i - 1]!;
    const [x1, y1] = WARP_STOPS[i]!;
    if (v <= x1) return y0 + ((v - x0) / (x1 - x0)) * (y1 - y0);
  }
  return 1;
}

/** 逆向映射（图高 → 真值比例）：刻度标签缺键兜底取整用。 */
export function unwarpValue(plot: number): number {
  const p = Math.min(1, Math.max(0, plot));
  for (let i = 1; i < WARP_STOPS.length; i += 1) {
    const [x0, y0] = WARP_STOPS[i - 1]!;
    const [x1, y1] = WARP_STOPS[i]!;
    if (p <= y1) return x0 + ((p - y0) / (y1 - y0)) * (x1 - x0);
  }
  return 1;
}

/** 刻度标签表（contract v5）：六等分图高刻度对应六个整值真值——刻度间距
 *  不等本身即非线性披露（log 轴惯例）。缺键回退 unwarp 取整百分数。 */
const WARP_TICK_LABELS: Record<number, string> = {
  0: "0%",
  0.2: "40%",
  0.4: "80%",
  0.6: "90%",
  0.8: "95%",
  1: "100%",
};

export function formatWarpTick(plot: number): string {
  return WARP_TICK_LABELS[Math.round(plot * 100) / 100] ?? `${(unwarpValue(plot) * 100).toFixed(0)}%`;
}

/** 横轴标签（contract v5）：day 档出 HH:mm、week/month 档出 MM-DD——
 *  序号轴下时间可读性由轴标签 + tooltip 承载。formatPointTime 切片。 */
export function formatAxisTime(ts: string, preset: SpanPreset): string {
  const [datePart, timePart] = formatPointTime(ts).split(" ");
  return preset === "day" ? (timePart ?? "") : (datePart ?? "");
}

/** 视窗预设 → 索引窗（contract v5）：start = 首个 ts ≥ 末点 − span 的索引；
 *  end 在索引域留右缘边距（孤点至少半槽，防贴死右缘）。 */
export function presetToIndexWindow(
  tsMsList: readonly number[],
  preset: SpanPreset,
): { start: number; end: number } {
  const last = tsMsList.length - 1;
  if (last < 0) return { start: 0, end: 0 };
  const cutoff = tsMsList[last]! - presetToSpanMs(preset);
  let start = last;
  for (let i = 0; i <= last; i += 1) {
    if (tsMsList[i]! >= cutoff) {
      start = i;
      break;
    }
  }
  return { start, end: last + Math.max(0.5, (last - start) * 0.02) };
}

/**
 * tooltip HTML（axis trigger，自定义模板 §4.4）：日期头 + 各指标值与环比箭头
 * （delta 对比同指标上一个非空点）+ 回退题型列表 + 点击提示。插值一律
 * escapeHtml（vector-canvas 先例），防 tooltip HTML 注入。
 */
export function buildTrendTooltipHtml(
  params: TrendTooltipParam[],
  points: readonly TrendPoint[],
  labels: TrendChartLabels,
  pickerSelected?: readonly string[],
): string {
  const first = params.find((param) => param.data)?.data;
  if (!first) return "";
  // 序号轴（contract v5）：datum.value[0] 即 run 序号索引，raw 即真值。
  const pointIndex = first.value[0];
  const point = points[pointIndex];
  if (!point) return "";
  const ts = point.ts;

  const rows = params.flatMap((param) => {
    const datum = param.data;
    const value = datum?.raw;
    if (!datum || value == null || !param.seriesName) return [];
    const key = datum.metricKey;
    // 环比：同指标上一个非空点（缺口不参与差值，保持「真实运行」语义）。
    let deltaHtml = "";
    for (let i = pointIndex - 1; i >= 0; i -= 1) {
      const prev = points[i]?.[key];
      if (prev != null) {
        const delta = value - prev;
        const arrow = delta >= 0 ? "↑" : "↓";
        const magnitude = `${(Math.abs(delta) * 100).toFixed(1)}%`;
        deltaHtml = ` <span style="opacity:.6">${arrow}${magnitude}</span>`;
        break;
      }
    }
    const color = escapeHtml(param.color ?? "#999");
    const marker =
      `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
      `background:${color};margin-right:4px"></span>`;
    return [
      `${marker}${escapeHtml(param.seriesName)}&nbsp;&nbsp;<b>${formatValue(value)}</b>${deltaHtml}`,
    ];
  });

  // 稀疏语义（spec §4.4）：选中的 picker 指标在该日期为 null（该档未跑）时不进
  // axis params（echarts 只为非空点生成 param）→ 显式补哑行，避免“勾了却无此行”。
  if (point && pickerSelected) {
    for (const key of pickerSelected) {
      const metric = PICKER_METRICS.find((m) => m.key === key);
      if (!metric || point[metric.key] != null) continue;
      const color = escapeHtml(metric.color);
      const marker =
        `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
        `background:${color};margin-right:4px"></span>`;
      rows.push(
        `${marker}${escapeHtml(labels[metric.labelKey])}&nbsp;&nbsp;` +
          `<span style="opacity:.6">${escapeHtml(labels.notRunInTier)}</span>`,
      );
    }
  }

  const lines = [`<div style="font-weight:600;margin-bottom:2px">${escapeHtml(formatPointTime(ts))}</div>`, ...rows];
  if (point?.regression?.detected && point.regression.categories.length > 0) {
    lines.push(
      `<div style="margin-top:2px;color:${REGRESSION_COLOR}">` +
        `${escapeHtml(labels.regressionPrefix)}: ` +
        `${point.regression.categories.map(escapeHtml).join(", ")}</div>`,
    );
  }
  // 基线更新语义（contract v5 修订）：竖线上文字退役后改由 tooltip 行承载。
  if (point?.is_baseline_update) {
    lines.push(`<div style="opacity:.75;margin-top:2px">${escapeHtml(labels.baselineUpdate)}</div>`);
  }
  lines.push(`<div style="opacity:.6;margin-top:2px">${escapeHtml(labels.clickForDetail)} →</div>`);
  return lines.join("<br/>");
}

export function buildChartOption(input: {
  points: TrendPoint[];
  baseline: TrendResponse["baseline"];
  labels: TrendChartLabels;
  dark?: boolean;
  /** picker 选中的稀疏指标键（会话级）——条件并入 series，不进图例。 */
  pickerSelected?: readonly string[];
  /** 图例开关回流态（echarts legendselectchanged）——仅服务 legend.selected
   *  回显（防 refetch 重建重置图例开关）；y 轴已固定全量程（contract v5）。 */
  legendSelected?: Record<string, boolean>;
  /** 横轴标签格式化（活读密度档：day 出 HH:mm、其余 MM-DD）；缺省月档。 */
  formatAxisTime?: (ts: string) => string;
}): EChartsCoreOption {
  const { points, baseline, labels, dark = false, pickerSelected, legendSelected, formatAxisTime: formatAxisTimeOverride } = input;
  const thresholdValue = baseline ? baseline.recall_at_k - baseline.threshold_percent / 100 : null;

  const metricSeries: LineSeriesOption[] = METRICS.map((metric) => ({
    name: labels[metric.labelKey],
    type: "line",
    // 逐序列点集（contract v4）：只取「该指标非空的 run」——快速档缺 layer2
    // 不打假缺口；线连接相邻实跑 run。序号轴（contract v5）：x = run 索引。
    data: points.flatMap((p, idx): TrendDatum[] => {
      const value = p[metric.key];
      if (value == null) return [];
      const datum: TrendDatum = {
        value: [idx, warpValue(value)],
        raw: value,
        runId: p.run_id,
        metricKey: metric.key,
      };
      // 回退标红只挂 Recall@k（CI 门禁指标）——由 regression.detected 驱动，
      // 与阈值线解耦（「线未破但点红」= category 级回退，§4.3.3 语义边界）。
      if (metric.key === "recall_at_k" && p.regression?.detected) {
        datum.itemStyle = { color: REGRESSION_COLOR };
      }
      return [datum];
    }),
    // 平滑（contract v5）：贝塞尔消硬拐点；极值过冲由 series 默认 clip 兜底。
    smooth: true,
    lineStyle:
      metric.layer === 1
        ? { color: metric.color, width: 2 }
        : { color: metric.color, width: 2, type: "dashed" },
    itemStyle: { color: metric.color },
    symbol: metric.layer === 1 ? "circle" : "emptyCircle",
    // 符号降档（contract v5 修订）：6 → 4，密集序号轴下减视觉噪声。
    symbolSize: 4,
    emphasis: { scale: 1.5 },
  }));

  // picker 稀疏系列（spec §4.3）：仅选中的候选并入，线型沿用 layer 语义（L1 实线
  // 实心圆 / L2 虚线空心圆）。不进 legend.data——picker 是独立多选入口，与图例六线
  // 的 defaultOn 开关语义分离，避免两处控制同一系列显隐。
  const pickerSeries: LineSeriesOption[] = PICKER_METRICS.filter((m) => pickerSelected?.includes(m.key)).map(
    (metric) => ({
      name: labels[metric.labelKey],
      type: "line",
      data: points.flatMap((p, idx): TrendDatum[] => {
        const value = p[metric.key];
        if (value == null) return [];
        return [{ value: [idx, warpValue(value)], raw: value, runId: p.run_id, metricKey: metric.key }];
      }),
      smooth: true,
      lineStyle:
        metric.layer === 1
          ? { color: metric.color, width: 2 }
          : { color: metric.color, width: 2, type: "dashed" },
      itemStyle: { color: metric.color },
      symbol: metric.layer === 1 ? "circle" : "emptyCircle",
      symbolSize: 4,
      emphasis: { scale: 1.5 },
    }),
  );

  // 标记系列：阈值横线（silent 不吃点击，避免 dataIndex 歧义）+ 基线更新竖线。
  // 系列名不进 legend.data，不出现在图例。baseline=null 且无基线更新点时不生成。
  const baselineDates = points.filter((p) => p.is_baseline_update).map((p) => p.ts);
  const markLineData: Record<string, unknown>[] = [];
  if (thresholdValue !== null && baseline) {
    // 阈值红虚线保留，但线上文字标注退役（2026-09-05）：insideEndTop 贴右端
    // 与贴顶的数据线重叠压线——文案改由 eval-tab 头部行红芯片承载。
    markLineData.push({
      // 阈值线纵坐标过 warp（contract v5）：与数据点同映射才贴合。
      yAxis: warpValue(thresholdValue),
      lineStyle: { color: REGRESSION_COLOR, type: "dashed", width: 1 },
    });
  }
  for (const date of baselineDates) {
    // 水平小字旗标（contract v5 修订三终态）：保留四字文案但改顶部留白带水平
    // 小字——position end + rotate 0 + distance 6，文字居中线顶上方（grid.top
    // 40 空带），不再随竖线旋转 90° 压 y 轴刻度（insideEndTop 旧弊）；
    // fontSize 11 → 10。四字小字半宽 ≈20px，左右 margin 60/40 容得下，边缘
    // run 无需额外对齐；tooltip 行保留作 hover 双载体。
    markLineData.push({
      xAxis: date,
      lineStyle: { color: ink(0.45, dark), type: "dashed", width: 1 },
      label: {
        position: "end",
        rotate: 0,
        distance: 6,
        align: "center",
        verticalAlign: "bottom",
        formatter: labels.baselineUpdate,
        color: ink(0.55, dark),
        fontSize: 10,
      },
    });
  }
  const markerSeries: LineSeriesOption[] =
    markLineData.length > 0
      ? [
          {
            name: labels.thresholdLine,
            type: "line",
            data: [],
            silent: true,
            markLine: { silent: true, symbol: "none", data: markLineData },
          },
        ]
      : [];

  return {
    // 滑条退役时底部只留图例高度（2026-09-05）；滑条在场时 74 档为轴标签
    // 与滑条各留独立带（contract v5 修订：60 档下标签带与滑条带重叠遮字）：
    // 轴线 74 → 标签 ≈52–66 → 滑条 28–42 → 图例 0–≈20。
    grid: { left: 60, right: 40, top: 40, bottom: points.length > DATA_ZOOM_MIN_POINTS ? 74 : 40 },
    legend: {
      // 窄栏溢出治理（2026-09-07）：plain 图例窄栏换行第二行时整行自 bottom:0
      // 锚点向上长，遮盖主图与滑条；改 scroll 单行翻页（echarts 窄容器降档）——
      // 容不下时出翻页箭头，行高恒定 ⇒ grid.bottom 的 40/60 两档恒成立。
      // 翻页控件随墨色，不引入新颜色词汇。
      type: "scroll",
      data: METRICS.map((m) => labels[m.labelKey]),
      bottom: 0,
      selected: Object.fromEntries(
        METRICS.map((m) => [labels[m.labelKey], legendSelected?.[labels[m.labelKey]] ?? m.defaultOn]),
      ),
      textStyle: { color: ink(0.75, dark) },
      pageIconColor: ink(0.75, dark),
      pageIconInactiveColor: ink(0.25, dark),
      pageTextStyle: { color: ink(0.75, dark) },
    },
    xAxis: {
      // 序号轴（contract v5）：每 run 一等距槽——不规则采样下时间等比间距
      // 是纯噪声（稀疏段拉空白、密集段挤右缘）；时间可读性改由轴标签
      // （密度档切 MM-DD ↔ HH:mm）+ tooltip（MM-DD HH:mm）承载。
      type: "category",
      data: points.map((p) => p.ts),
      boundaryGap: false,
      axisLabel: {
        color: ink(0.55, dark),
        formatter: formatAxisTimeOverride ?? ((ts: string) => formatAxisTime(ts, "month")),
      },
      axisLine: { lineStyle: { color: ink(0.3, dark) } },
    },
    yAxis: {
      // 固定全量程 + 分段加权（contract v5）：六等分刻度落冻结标签表
      // （0/40/80/90/95/100%）；y 轴自适应退役（spec 2026-08-24 §4.6）——
      // 0–100 恒全现，勾图例不再轴程跳变。
      type: "value",
      min: 0,
      max: 1,
      interval: 0.2,
      axisLabel: {
        formatter: formatWarpTick,
        color: ink(0.55, dark),
      },
      splitLine: { lineStyle: { type: "dashed", color: ink(dark ? 0.1 : 0.06, dark) } },
    },
    series: [...metricSeries, ...pickerSeries, ...markerSeries],
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: dark ? "rgba(24,24,30,0.85)" : "rgba(255,255,255,0.9)",
      borderColor: dark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.08)",
      textStyle: { fontSize: 11, color: ink(0.85, dark) },
      formatter: (params: unknown) =>
        buildTrendTooltipHtml(params as TrendTooltipParam[], points, labels, pickerSelected),
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      // 滑条细带化（contract v5 二段修订）：20 → 14 细带（与 sparkline 28×12、
      // 进度条 h-1 同细带词汇，降视觉权重）；bottom 30 → 28，与标签带留
      // 10px、与图例带留 8px。
      ...(points.length > DATA_ZOOM_MIN_POINTS
        ? [{ type: "slider" as const, xAxisIndex: 0, height: 14, bottom: 28 }]
        : []),
    ],
  };
}
