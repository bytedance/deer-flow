/**
 * 评测趋势图 option 纯函数（contract v4，spec 2026-09-07 §2/§3）：
 * - run 级点：datum 携带 runId（点与 run 一一对应），click 从 params.data
 *   取数、不依赖 dataIndex；
 * - 逐序列点集：只取「该指标非空的 run」——缺层不打假缺口；
 * - 6 条图例 series（Layer 1 实线实心圆 / Layer 2 虚线空心圆，默认只显示
 *   Recall@k + Hit Rate）+ 经 picker 条件并入的 4 条稀疏指标线（不进图例）；
 * - 阈值线 = baseline.recall_at_k - threshold_percent/100；baseline=null 不生成；
 * - 回退点项级 itemStyle 标红由 regression.detected 驱动（per-category 门禁
 *   口径），与阈值线解耦；
 * - 纵轴分段加权 warp（contract v5）：固定全量程 0–1，六等分刻度落冻结
 *   标签表 0/40/80/90/95/100%（y 轴自适应退役）；
 * - 基线更新点（is_baseline_update）画竖线；
 * - 横轴序号 category（contract v5）：每 run 一等距槽，标签按密度档切
 *   MM-DD ↔ HH:mm（时间可读性承载面）；
 * - 全线 smooth 消硬拐点（contract v5）；
 * - 缩放密度档 / 视窗预设纯函数（resolveShowSymbol / presetToSpanMs /
 *   spanToPreset / presetToIndexWindow）；
 * - tooltip 一律 escapeHtml，头为命中 run 的本地 MM-DD HH:mm，行报真值 raw。
 */
import { describe, expect, it } from "@rstest/core";

import {
  buildChartOption,
  buildTrendTooltipHtml,
  escapeHtml,
  formatAxisTime,
  PICKER_METRICS,
  presetToIndexWindow,
  presetToSpanMs,
  resolveShowSymbol,
  spanToPreset,
  unwarpValue,
  warpValue,
  type TrendTooltipParam,
} from "@/components/workspace/knowledge/eval-trend-chart.utils";
import type { TrendChartLabels, TrendPoint, TrendResponse } from "@/core/knowledge/types";

const LABELS: TrendChartLabels = {
  recallAtK: "召回率@k",
  hitRate: "命中率",
  mrr: "MRR",
  faithfulness: "忠实度",
  answerRelevancy: "相关性",
  contextPrecision: "精确率",
  pathAccuracy: "路径准确率",
  citationPrecision: "引用准确率",
  citationRecall: "引用召回率",
  seedHitRate: "实体命中率",
  routingHitRate: "路由命中率",
  thresholdLine: "回退阈值线",
  thresholdLabel: (p) => `回退阈值 -${p}%`,
  baselineUpdate: "基线更新",
  clickForDetail: "点击查看详情",
  regressionPrefix: "回退题型",
  notRunInTier: "该档未跑",
};

function point(overrides: Partial<TrendPoint> = {}): TrendPoint {
  return {
    ts: "2026-08-20T09:00:00+00:00",
    recall_at_k: 0.9,
    hit_rate: 0.92,
    mrr: 0.81,
    path_accuracy: 0.95,
    faithfulness: 0.93,
    answer_relevancy: 0.87,
    context_precision: 0.85,
    citation_precision: 0.9,
    citation_recall: 0.85,
    seed_hit_rate: 0.8,
    routing_hit_rate: 0.87,
    run_id: "run-1",
    regression: null,
    is_baseline_update: false,
    ...overrides,
  };
}

const BASELINE: NonNullable<TrendResponse["baseline"]> = {
  recall_at_k: 0.9,
  threshold_percent: 3,
};

interface SeriesLike {
  name: string;
  type: string;
  smooth?: boolean;
  symbolSize?: number;
  lineStyle?: { color?: string; type?: string; width?: number };
  symbol?: string;
  data?: { value: [number, number]; raw: number; runId: string; itemStyle?: { color: string } }[];
  markLine?: { silent?: boolean; data: Record<string, unknown>[] };
}

function buildOption(
  points: TrendPoint[],
  baseline: TrendResponse["baseline"] = BASELINE,
  extra: { pickerSelected?: string[]; legendSelected?: Record<string, boolean> } = {},
) {
  return buildChartOption({ points, baseline, labels: LABELS, dark: false, ...extra }) as {
    legend: { type: string; data: string[]; selected: Record<string, boolean> };
    yAxis: { min: number; max: number; interval: number; axisLabel: { formatter: (v: number) => string } };
    xAxis: { type: string; data: string[]; boundaryGap: boolean; axisLabel: { formatter?: (ts: string) => string } };
    series: SeriesLike[];
  };
}

describe("buildChartOption 指标线配置", () => {
  it("generates 6 metric series with spec §4.3.2 colors and line styles", () => {
    const option = buildOption([point()]);
    const metric = option.series.filter((s) => !s.markLine);
    expect(metric).toHaveLength(6);

    const byName = new Map(metric.map((s) => [s.name, s]));
    // Layer 1：实线 + 实心圆
    expect(byName.get("召回率@k")?.lineStyle).toMatchObject({ color: "#3B82F6", width: 2 });
    expect(byName.get("召回率@k")?.lineStyle?.type).toBeUndefined();
    expect(byName.get("召回率@k")?.symbol).toBe("circle");
    expect(byName.get("命中率")?.lineStyle).toMatchObject({ color: "#10B981" });
    expect(byName.get("MRR")?.lineStyle).toMatchObject({ color: "#8B5CF6" });
    // Layer 2：虚线 + 空心圆
    expect(byName.get("忠实度")?.lineStyle).toMatchObject({ color: "#F59E0B", type: "dashed" });
    expect(byName.get("忠实度")?.symbol).toBe("emptyCircle");
    expect(byName.get("相关性")?.lineStyle).toMatchObject({ color: "#EC4899", type: "dashed" });
    expect(byName.get("精确率")?.lineStyle).toMatchObject({ color: "#06B6D4", type: "dashed" });
    // 平滑（contract v5）：全线贝塞尔消硬拐点
    expect(byName.get("召回率@k")?.smooth).toBe(true);
    expect(byName.get("忠实度")?.smooth).toBe(true);
    // 符号降档（contract v5 修订）：6 → 4
    expect(byName.get("召回率@k")?.symbolSize).toBe(4);
    expect(byName.get("忠实度")?.symbolSize).toBe(4);
  });

  it("legend defaults: only Recall@k + Hit Rate visible", () => {
    const option = buildOption([point()]);
    expect(option.legend.data).toEqual([
      "召回率@k",
      "命中率",
      "MRR",
      "忠实度",
      "相关性",
      "精确率",
    ]);
    expect(option.legend.selected).toEqual({
      "召回率@k": true,
      命中率: true,
      MRR: false,
      忠实度: false,
      相关性: false,
      精确率: false,
    });
    // 窄栏治理（2026-09-07）：scroll 单行翻页——plain 换行第二行遮盖主图退役。
    expect(option.legend.type).toBe("scroll");
  });

  it("hides the slider dataZoom when points are sparse (2026-09-05)", () => {
    // 点数稀疏（≤8）时常驻滑条纯噪声：只留 inside 缩放，grid 底部不留滑条空槽。
    const sparse = buildChartOption({
      points: [point()],
      baseline: BASELINE,
      labels: LABELS,
    }) as { dataZoom: { type: string; height?: number; bottom?: number }[]; grid: { bottom: number } };
    expect(sparse.dataZoom.map((d) => d.type)).toEqual(["inside"]);
    expect(sparse.grid.bottom).toBe(40);
    // 点数充足时滑条回归（点数现为 run 数）。
    const dense = buildChartOption({
      points: Array.from({ length: 9 }, (_, i) => point({ ts: `2026-08-${10 + i}T09:00:00+00:00`, run_id: `run-${i}` })),
      baseline: BASELINE,
      labels: LABELS,
    }) as { dataZoom: { type: string; height?: number; bottom?: number }[]; grid: { bottom: number } };
    expect(dense.dataZoom.map((d) => d.type)).toContain("slider");
    // 滑条在场 74 档（contract v5 修订）：轴标签带与滑条带各留独立带防遮字
    expect(dense.grid.bottom).toBe(74);
    // 滑条细带化（contract v5 二段修订）：14 高 / bottom 28
    const slider = dense.dataZoom.find((d) => d.type === "slider");
    expect(slider?.height).toBe(14);
    expect(slider?.bottom).toBe(28);
  });

  it("attaches the point's own run_id to every series datum (contract v4)", () => {
    const option = buildOption([
      point({ run_id: "run-a" }),
      point({ ts: "2026-08-21T09:00:00+00:00", run_id: "run-b", faithfulness: null }),
    ]);
    const byName = new Map(option.series.filter((s) => !s.markLine).map((s) => [s.name, s]));
    expect(byName.get("召回率@k")?.data?.map((d) => d.runId)).toEqual(["run-a", "run-b"]);
    expect(byName.get("MRR")?.data?.map((d) => d.runId)).toEqual(["run-a", "run-b"]);
    // 序号轴 datum（contract v5）：[全局序号, warp 图高] + raw 真值
    expect(byName.get("召回率@k")?.data?.map((d) => d.value)).toEqual([
      [0, warpValue(0.9)],
      [1, warpValue(0.9)],
    ]);
    expect(byName.get("召回率@k")?.data?.map((d) => d.raw)).toEqual([0.9, 0.9]);
    // run-b 缺 layer2：忠实度序列只含 run-a，索引仍为全局序号 0
    expect(byName.get("忠实度")?.data?.map((d) => d.runId)).toEqual(["run-a"]);
    expect(byName.get("忠实度")?.data?.[0]?.value).toEqual([0, warpValue(0.93)]);
  });

  it("per-series point sets skip null runs (contract v4: no fake gaps)", () => {
    const option = buildOption([point({ recall_at_k: null, faithfulness: null })]);
    const byName = new Map(option.series.filter((s) => !s.markLine).map((s) => [s.name, s]));
    // 缺测 run 不进该序列点集——线连接相邻实跑 run，不打假缺口
    expect(byName.get("召回率@k")?.data).toHaveLength(0);
    expect(byName.get("忠实度")?.data).toHaveLength(0);
    // 同 run 的其它指标照常进各自序列
    expect(byName.get("命中率")?.data).toHaveLength(1);
    expect((byName.get("召回率@k") as Record<string, unknown> | undefined)?.connectNulls).toBeUndefined();
  });
});

describe("buildChartOption picker 稀疏指标线（spec §4.3，plan Task 4）", () => {
  it("PICKER_METRICS 冻结 5 个稀疏候选与 spec 色/层", () => {
    expect(PICKER_METRICS.map((m) => m.key)).toEqual([
      "path_accuracy",
      "citation_precision",
      "citation_recall",
      "seed_hit_rate",
      "routing_hit_rate",
    ]);
    const byKey = new Map(PICKER_METRICS.map((m) => [m.key, m]));
    expect(byKey.get("path_accuracy")).toMatchObject({ color: "#84CC16", layer: 1 });
    expect(byKey.get("citation_precision")).toMatchObject({ color: "#F97316", layer: 2 });
    expect(byKey.get("citation_recall")).toMatchObject({ color: "#14B8A6", layer: 2 });
    expect(byKey.get("seed_hit_rate")).toMatchObject({ color: "#A855F7", layer: 2 });
    expect(byKey.get("routing_hit_rate")).toMatchObject({ color: "#64748B", layer: 2 });
  });

  it("仅在选中时并入 picker 系列，且不进 legend.data（不脏图例）", () => {
    const without = buildOption([point()]);
    expect(without.series.filter((s) => !s.markLine).map((s) => s.name)).not.toContain("引用准确率");
    expect(without.legend.data).toHaveLength(6);

    const withPicker = buildOption([point()], BASELINE, { pickerSelected: ["citation_precision"] });
    const names = withPicker.series.filter((s) => !s.markLine).map((s) => s.name);
    expect(names).toContain("引用准确率");
    // picker 系列不进 legend.data / legend.selected
    expect(withPicker.legend.data).not.toContain("引用准确率");
    expect(withPicker.legend.data).toHaveLength(6);
  });

  it("picker 线型沿用 layer 语义（L1 实线实心 / L2 虚线空心）", () => {
    const option = buildOption([point()], BASELINE, {
      pickerSelected: ["path_accuracy", "citation_precision", "citation_recall", "seed_hit_rate", "routing_hit_rate"],
    });
    const byName = new Map(option.series.filter((s) => !s.markLine).map((s) => [s.name, s]));
    expect(byName.get("路径准确率")?.lineStyle).toMatchObject({ color: "#84CC16", width: 2 });
    expect(byName.get("路径准确率")?.lineStyle?.type).toBeUndefined();
    expect(byName.get("路径准确率")?.symbol).toBe("circle");
    expect(byName.get("引用准确率")?.lineStyle).toMatchObject({ color: "#F97316", type: "dashed" });
    expect(byName.get("引用准确率")?.symbol).toBe("emptyCircle");
    expect(byName.get("引用召回率")?.lineStyle).toMatchObject({ color: "#14B8A6", type: "dashed" });
    expect(byName.get("实体命中率")?.lineStyle).toMatchObject({ color: "#A855F7", type: "dashed" });
    // 路由命中率：L2 虚线空心圆 + slate 中性色
    expect(byName.get("路由命中率")?.lineStyle).toMatchObject({ color: "#64748B", type: "dashed" });
  });

  it("picker 系列 runId 取本 run（contract v4 单键）", () => {
    const option = buildOption([point({ run_id: "run-x" })], BASELINE, {
      pickerSelected: ["path_accuracy", "citation_precision"],
    });
    const byName = new Map(option.series.filter((s) => !s.markLine).map((s) => [s.name, s]));
    expect(byName.get("路径准确率")?.data?.[0]?.runId).toBe("run-x");
    expect(byName.get("引用准确率")?.data?.[0]?.runId).toBe("run-x");
  });
});

describe("buildChartOption 阈值线与异常标记", () => {
  it("draws threshold line at baseline.recall_at_k - threshold_percent/100", () => {
    const option = buildOption([point()], { recall_at_k: 0.9, threshold_percent: 3 });
    const marker = option.series.find((s) => s.markLine);
    expect(marker).toBeDefined();
    expect(marker?.markLine?.silent).toBe(true);
    const horizontal = marker?.markLine?.data.find((d) => "yAxis" in d);
    // 阈值线纵坐标过 warp（contract v5）：0.87 ∈ [0.8,0.9] → 0.4+0.7×0.2 = 0.54
    expect(horizontal?.yAxis).toBeCloseTo(warpValue(0.87), 5);
    expect(horizontal?.yAxis).toBeCloseTo(0.54, 5);
    // 线上文字标注退役（2026-09-05）：insideEndTop 贴右端与贴顶数据线重叠
    // 压线——文案改由 eval-tab 头部行红芯片承载（eval-threshold-chip）。
    expect(horizontal?.label).toBeUndefined();
  });

  it("omits the markLine series entirely when baseline is null", () => {
    const option = buildOption([point()], null);
    expect(option.series.filter((s) => s.markLine)).toHaveLength(0);
  });

  it("marks regression points red on the Recall@k series only (per-category gate)", () => {
    const option = buildOption([
      point({ regression: { detected: true, categories: ["global"] } }),
      point({ ts: "2026-08-21T09:00:00+00:00", run_id: "run-2", regression: { detected: false, categories: [] } }),
    ]);
    const byName = new Map(option.series.filter((s) => !s.markLine).map((s) => [s.name, s]));
    expect(byName.get("召回率@k")?.data?.[0]?.itemStyle?.color).toBe("#EF4444");
    expect(byName.get("召回率@k")?.data?.[1]?.itemStyle).toBeUndefined();
    // 回退标红只挂 Recall@k（门禁指标），Hit Rate 等其他线不染红
    expect(byName.get("命中率")?.data?.[0]?.itemStyle).toBeUndefined();
  });

  it("draws a vertical markLine for is_baseline_update points", () => {
    const option = buildOption([point({ is_baseline_update: true })]);
    const marker = option.series.find((s) => s.markLine);
    const vertical = marker?.markLine?.data.find((d) => "xAxis" in d);
    expect(vertical?.xAxis).toBe("2026-08-20T09:00:00+00:00");
    // 水平小字旗标（contract v5 修订三终态）：position end + rotate 0 +
    // fontSize 10——文字在顶部留白带水平排列，不再随线旋转 90° 压 y 轴刻度
    const label = vertical?.label as { position?: string; rotate?: number; fontSize?: number; formatter?: string };
    expect(label?.position).toBe("end");
    expect(label?.rotate).toBe(0);
    expect(label?.fontSize).toBe(10);
    expect(label?.formatter).toBe("基线更新");
  });

  it("keeps vertical baseline-update lines when threshold is absent", () => {
    // baseline 行存在但被标记运行不在阈值窗口内等边缘情况：竖线仍应出现
    const option = buildOption([point({ is_baseline_update: true })], null);
    const marker = option.series.find((s) => s.markLine);
    expect(marker?.markLine?.data.some((d) => "xAxis" in d && d.xAxis === "2026-08-20T09:00:00+00:00")).toBe(true);
  });
});

describe("buildChartOption 坐标轴（contract v5：序号横轴 + warp 纵轴）", () => {
  it("y 轴固定全量程 + 六等分刻度落冻结标签表", () => {
    const option = buildOption([point()]);
    expect(option.yAxis.min).toBe(0);
    expect(option.yAxis.max).toBe(1);
    expect(option.yAxis.interval).toBe(0.2);
    const fmt = option.yAxis.axisLabel.formatter;
    expect(fmt(0)).toBe("0%");
    expect(fmt(0.2)).toBe("40%");
    expect(fmt(0.4)).toBe("80%");
    expect(fmt(0.6)).toBe("90%");
    expect(fmt(0.8)).toBe("95%");
    expect(fmt(1)).toBe("100%");
  });

  it("warpValue/unwarpValue 分段线性折点钉桩（权重 20/20/60）", () => {
    expect(warpValue(0)).toBe(0);
    expect(warpValue(0.4)).toBeCloseTo(0.2, 5);
    expect(warpValue(0.5)).toBeCloseTo(0.25, 5);
    expect(warpValue(0.8)).toBeCloseTo(0.4, 5);
    expect(warpValue(0.9)).toBeCloseTo(0.6, 5);
    expect(warpValue(0.95)).toBeCloseTo(0.8, 5);
    expect(warpValue(1)).toBe(1);
    // clamp：越界入参不出界
    expect(warpValue(1.2)).toBe(1);
    expect(warpValue(-0.3)).toBe(0);
    // 逆映射回环
    expect(unwarpValue(0.4)).toBeCloseTo(0.8, 5);
    expect(unwarpValue(0.6)).toBeCloseTo(0.9, 5);
    expect(warpValue(unwarpValue(0.7))).toBeCloseTo(0.7, 5);
  });

  it("x 轴为序号 category 轴：每 run 一等距槽，标签承载时间", () => {
    const points = [point(), point({ ts: "2026-08-21T09:00:00+00:00", run_id: "run-2" })];
    const option = buildOption(points);
    expect(option.xAxis.type).toBe("category");
    expect(option.xAxis.data).toEqual(["2026-08-20T09:00:00+00:00", "2026-08-21T09:00:00+00:00"]);
    expect(option.xAxis.boundaryGap).toBe(false);
    // 默认月档出 MM-DD；formatAxisTime 纯函数钉桩 day 出 HH:mm
    const fmt = option.xAxis.axisLabel.formatter;
    expect(fmt?.("2026-08-20T09:00:00+00:00")).toMatch(/^\d{2}-\d{2}$/);
    expect(formatAxisTime("2026-08-20T09:00:00+00:00", "day")).toMatch(/^\d{2}:\d{2}$/);
    expect(formatAxisTime("2026-08-20T09:00:00+00:00", "week")).toMatch(/^\d{2}-\d{2}$/);
  });

  it("dark mode flips decoration colors (axis label color differs from light)", () => {
    const light = buildOption([point()]);
    const dark = buildChartOption({
      points: [point()],
      baseline: BASELINE,
      labels: LABELS,
      dark: true,
    }) as { xAxis: { axisLabel: { color: string } } };
    expect(dark.xAxis.axisLabel.color).not.toBe(
      (light as unknown as { xAxis: { axisLabel: { color: string } } }).xAxis.axisLabel.color,
    );
  });
});

describe("缩放密度与视窗预设纯函数（contract v4，spec 2026-09-07 §3）", () => {
  it("resolveShowSymbol：可见 run ≤80 出点 / >80 隐点", () => {
    expect(resolveShowSymbol(1)).toBe(true);
    expect(resolveShowSymbol(80)).toBe(true);
    expect(resolveShowSymbol(81)).toBe(false);
  });

  it("presetToSpanMs：日/周/月 = 24h/7d/30d", () => {
    expect(presetToSpanMs("day")).toBe(24 * 3_600_000);
    expect(presetToSpanMs("week")).toBe(7 * 24 * 3_600_000);
    expect(presetToSpanMs("month")).toBe(30 * 24 * 3_600_000);
  });

  it("spanToPreset：≤36h=day / ≤14d=week / 其余=month", () => {
    expect(spanToPreset(24 * 3_600_000)).toBe("day");
    expect(spanToPreset(36 * 3_600_000)).toBe("day");
    expect(spanToPreset(36 * 3_600_000 + 1)).toBe("week");
    expect(spanToPreset(14 * 24 * 3_600_000)).toBe("week");
    expect(spanToPreset(14 * 24 * 3_600_000 + 1)).toBe("month");
    expect(spanToPreset(90 * 24 * 3_600_000)).toBe("month");
  });

  it("presetToIndexWindow：day 档 start = 末点 24h 内首个索引，end 留索引边距", () => {
    const hour = 3_600_000;
    const t0 = new Date("2026-08-01T00:00:00+00:00").getTime();
    const list = [t0, t0 + 25 * hour, t0 + 26 * hour, t0 + 49 * hour];
    // cutoff = t0+49h−24h = t0+25h → start=1；end = 3 + max(0.5, 2×0.02) = 3.5
    expect(presetToIndexWindow(list, "day")).toEqual({ start: 1, end: 3.5 });
  });

  it("presetToIndexWindow：month 档覆盖全点；孤点 end 边距半槽；空集安全", () => {
    const hour = 3_600_000;
    const t0 = new Date("2026-08-01T00:00:00+00:00").getTime();
    const list = [t0, t0 + 25 * hour, t0 + 26 * hour, t0 + 49 * hour];
    expect(presetToIndexWindow(list, "month")).toEqual({ start: 0, end: 3.5 });
    expect(presetToIndexWindow([t0], "day")).toEqual({ start: 0, end: 0.5 });
    expect(presetToIndexWindow([], "day")).toEqual({ start: 0, end: 0 });
  });
});

describe("buildTrendTooltipHtml", () => {
  function paramsFor(points: TrendPoint[], ts: string, seriesNames: string[]): TrendTooltipParam[] {
    const byLabel: Record<string, keyof TrendPoint> = {
      "召回率@k": "recall_at_k",
      命中率: "hit_rate",
      MRR: "mrr",
      忠实度: "faithfulness",
      相关性: "answer_relevancy",
      精确率: "context_precision",
    };
    const p = points.find((pt) => pt.ts === ts);
    if (!p) throw new Error(`no point at ${ts}`);
    const index = points.indexOf(p);
    return seriesNames.map((name) => {
      const key = byLabel[name] as "recall_at_k";
      const raw = p[key];
      return {
        seriesName: name,
        color: "#3B82F6",
        data: {
          // 序号轴 datum（contract v5）：[序号, warp 图高] + raw 真值
          value: [index, warpValue(raw ?? 0)],
          raw,
          runId: p.run_id,
          metricKey: key,
        } as TrendTooltipParam["data"],
      };
    });
  }

  it("renders local-time header and percent for every metric (contract v4)", () => {
    const points = [point()];
    const html = buildTrendTooltipHtml(paramsFor(points, "2026-08-20T09:00:00+00:00", ["召回率@k", "MRR", "忠实度"]), points, LABELS);
    // 头为命中 run 的本地 MM-DD HH:mm（非裸日期/裸 ts）——时区本地化，格式钉桩
    expect(html).toMatch(/\d{2}-\d{2} \d{2}:\d{2}/);
    expect(html).toContain("90.0%"); // recall_at_k 0.9
    expect(html).toContain("81.0%"); // mrr 0.81 → 百分数（三位小数退役）
    expect(html).toContain("93.0%"); // faithfulness 0.93 → 百分数
    expect(html).toContain("点击查看详情");
  });

  it("shows delta arrows against the previous point with the same metric", () => {
    const points = [
      point({ ts: "2026-08-19T09:00:00+00:00", run_id: "run-1", recall_at_k: 0.923 }),
      point({ ts: "2026-08-20T09:00:00+00:00", run_id: "run-2", recall_at_k: 0.9 }), // ↓2.3%
    ];
    const html = buildTrendTooltipHtml(paramsFor(points, "2026-08-20T09:00:00+00:00", ["召回率@k"]), points, LABELS);
    expect(html).toContain("↓2.3%");
    const prev = buildTrendTooltipHtml(paramsFor(points, "2026-08-19T09:00:00+00:00", ["召回率@k"]), points, LABELS);
    expect(prev).not.toContain("↑");
    expect(prev).not.toContain("↓");
  });

  it("skips series whose value is null at this run", () => {
    const points = [point({ faithfulness: null })];
    const html = buildTrendTooltipHtml(paramsFor(points, "2026-08-20T09:00:00+00:00", ["召回率@k", "忠实度"]), points, LABELS);
    expect(html).toContain("召回率@k");
    expect(html).not.toContain("忠实度");
  });

  it("为选中但 null 的 picker 指标补‘该档未跑’哑行（spec §4.4）", () => {
    const points = [point({ citation_precision: null })];
    const html = buildTrendTooltipHtml(
      paramsFor(points, "2026-08-20T09:00:00+00:00", ["召回率@k"]),
      points,
      LABELS,
      ["citation_precision"],
    );
    expect(html).toContain("引用准确率");
    expect(html).toContain("该档未跑");
  });

  it("选中 picker 指标有值时不补哑行（由 echarts 正常入 params）", () => {
    const points = [point({ citation_precision: 0.9 })];
    const html = buildTrendTooltipHtml(
      paramsFor(points, "2026-08-20T09:00:00+00:00", ["召回率@k"]),
      points,
      LABELS,
      ["citation_precision"],
    );
    expect(html).not.toContain("该档未跑");
  });

  it("lists regressed categories when regression.detected", () => {
    const points = [point({ regression: { detected: true, categories: ["global", "relation"] } })];
    const html = buildTrendTooltipHtml(paramsFor(points, "2026-08-20T09:00:00+00:00", ["召回率@k"]), points, LABELS);
    expect(html).toContain("回退题型");
    expect(html).toContain("global");
    expect(html).toContain("relation");
  });

  it("补‘基线更新’行于 is_baseline_update 点（contract v5 修订：竖线文字退役）", () => {
    const points = [point({ is_baseline_update: true })];
    const html = buildTrendTooltipHtml(paramsFor(points, "2026-08-20T09:00:00+00:00", ["召回率@k"]), points, LABELS);
    expect(html).toContain("基线更新");
    const plain = [point()];
    const plainHtml = buildTrendTooltipHtml(paramsFor(plain, "2026-08-20T09:00:00+00:00", ["召回率@k"]), plain, LABELS);
    expect(plainHtml).not.toContain("基线更新");
  });

  it("escapes HTML in ts, series names and category names", () => {
    const evil: TrendChartLabels = { ...LABELS, recallAtK: "<img src=x onerror=alert(1)>" };
    const points = [point({ ts: "2026-08-20T09:00:00+00:00<script>", regression: { detected: true, categories: ["<b>global</b>"] } })];
    const html = buildTrendTooltipHtml(
      [
        {
          seriesName: "<img src=x onerror=alert(1)>",
          color: "#3B82F6",
          data: { value: [0, 0.5], raw: 0.9, runId: "r", metricKey: "recall_at_k" },
        },
      ],
      points,
      evil,
    );
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script>");
    // 用户输入的 <b>global</b> 必须被转义（tooltip 模板自身的 <b> 数值标签除外）
    expect(html).not.toContain("<b>global</b>");
    expect(html).toContain("&lt;b&gt;global&lt;/b&gt;");
    expect(html).toContain("&lt;img");
  });
});

describe("escapeHtml", () => {
  it("escapes &, <, > and quotes", () => {
    expect(escapeHtml(`a&b<c>d"e`)).toBe("a&amp;b&lt;c&gt;d&quot;e");
  });
});
