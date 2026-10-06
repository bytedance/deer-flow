/**
 * 评测趋势图 canvas 组件（contract v4，spec 2026-09-07 §2/§3）：
 * jsdom 不可运行 echarts——mock echarts/core 适配层（对齐 graph-tab.dom.test
 * 的 canvas mock 基建），断言：
 * - props（points/baseline/labels）经 buildChartOption 透传进 setOption；
 * - 点击事件从 datum.runId 取数（不依赖 dataIndex——阈值线/多 series 下索引
 *   不对齐），无 runId 的点击（markLine 等）不触发回调；
 * - 缩放密度档（contract v5 索引域）：datazoom 事件 → 可见 run 数 → 逐 series
 *   patch showSymbol + 跨度回算预设上抛 onSpanChange；
 * - 视窗预设点击请求（spanRequest nonce）→ setOption dataZoom 索引窗。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import EvalTrendChart from "@/components/workspace/knowledge/eval-trend-chart";
import { warpValue } from "@/components/workspace/knowledge/eval-trend-chart.utils";
import type { TrendChartLabels, TrendPoint, TrendResponse } from "@/core/knowledge/types";

/** echarts 适配层 mock：捕获 setOption 入参与事件处理器，不碰真实 canvas。
 *  getOption 返回浅合并后的最新 state——密度档逻辑读 dataZoom/series 用。 */
const echartsMock = rs.hoisted(() => {
  const handlers = new Map<string, ((params: unknown) => void)[]>();
  return {
    handlers,
    setOptionCalls: [] as { option: Record<string, unknown>; opts?: unknown }[],
    use: rs.fn(),
    init: rs.fn(() => {
      let state: Record<string, unknown> = {};
      return {
        on: (event: string, cb: (params: unknown) => void) => {
          handlers.set(event, [...(handlers.get(event) ?? []), cb]);
        },
        getOption: () => state,
        setOption: (option: Record<string, unknown>, opts?: unknown) => {
          state = { ...state, ...option };
          echartsMock.setOptionCalls.push({ option, opts });
        },
        resize: rs.fn(),
        dispose: rs.fn(),
      };
    }),
  };
});

rs.mock("echarts/core", () => echartsMock);

// jsdom 无 ResizeObserver——组件 resize 监听用空实现顶替（panels-shell 先例）。
class ResizeObserverStub {
  observe() {
    /* no-op stub */
  }
  unobserve() {
    /* no-op stub */
  }
  disconnect() {
    /* no-op stub */
  }
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= ResizeObserverStub;

const LABELS: TrendChartLabels = {
  recallAtK: "Recall@k",
  hitRate: "命中率",
  mrr: "MRR",
  faithfulness: "忠实度",
  answerRelevancy: "答案相关性",
  contextPrecision: "上下文精度",
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

const POINTS: TrendPoint[] = [point()];

const BASELINE: NonNullable<TrendResponse["baseline"]> = {
  recall_at_k: 0.9,
  threshold_percent: 3,
};

interface SeriesLike {
  name: string;
  data?: { value: [number, number]; raw: number; runId: string }[];
  markLine?: { data: Record<string, unknown>[] };
}

/** 最后一次「整表 option」调用（含 legend）——密度档/视窗的 patch 调用不含 legend。 */
function lastOption() {
  const call = [...echartsMock.setOptionCalls].reverse().find((c) => "legend" in c.option);
  if (!call) throw new Error("setOption was not called with a full option");
  return call.option as {
    legend: { selected: Record<string, boolean> };
    xAxis: { type: string; data: string[]; axisLabel: { formatter?: (ts: string) => string } };
    series: SeriesLike[];
  };
}

describe("EvalTrendChart", () => {
  beforeEach(() => {
    echartsMock.setOptionCalls.length = 0;
    echartsMock.handlers.clear();
    echartsMock.init.mockClear();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the container and inits echarts once", () => {
    render(<EvalTrendChart points={POINTS} baseline={BASELINE} labels={LABELS} />);
    expect(screen.getByTestId("eval-trend-chart")).toBeTruthy();
    expect(echartsMock.init).toHaveBeenCalledTimes(1);
    expect(echartsMock.setOptionCalls.length).toBeGreaterThan(0);
  });

  it("passes props through into the chart option (series, legend, threshold)", () => {
    render(<EvalTrendChart points={POINTS} baseline={BASELINE} labels={LABELS} />);
    const option = lastOption();
    // 6 条指标线 + 1 条阈值线系列
    expect(option.series).toHaveLength(7);
    const recall = option.series.find((s) => s.name === "Recall@k");
    expect(recall?.data?.[0]?.runId).toBe("run-1");
    // 序号轴 datum（contract v5）：[序号 0, warp 图高] + raw 真值
    expect(recall?.data?.[0]?.value).toEqual([0, warpValue(0.9)]);
    expect(recall?.data?.[0]?.raw).toBe(0.9);
    // 图例默认显隐：Recall@k + 命中率 开，其余关
    expect(option.legend.selected).toMatchObject({ "Recall@k": true, 命中率: true, MRR: false });
    // 阈值线过 warp：0.87 → 0.54
    const marker = option.series.find((s) => s.markLine);
    expect(marker?.markLine?.data.some((d) => "yAxis" in d && Number(d.yAxis) === warpValue(0.87))).toBe(true);
    // contract v5：序号 category 轴，category 数据 = run ts 列表，标签 formatter 活读密度档
    expect(option.xAxis.type).toBe("category");
    expect(option.xAxis.data).toEqual(["2026-08-20T09:00:00+00:00"]);
    expect(typeof option.xAxis.axisLabel.formatter).toBe("function");
  });

  it("baseline=null 时不生成阈值线系列", () => {
    render(<EvalTrendChart points={POINTS} baseline={null} labels={LABELS} />);
    const option = lastOption();
    expect(option.series.filter((s) => s.markLine)).toHaveLength(0);
  });

  it("click on a datum with runId fires onPointClick; runId-less clicks do not", () => {
    const onPointClick = rs.fn();
    render(
      <EvalTrendChart
        points={POINTS}
        baseline={BASELINE}
        labels={LABELS}
        onPointClick={onPointClick}
      />,
    );
    const clickHandlers = echartsMock.handlers.get("click") ?? [];
    expect(clickHandlers.length).toBeGreaterThan(0);
    // 数据点：datum 携带 runId → 回调
    clickHandlers.forEach((cb) => cb({ data: { value: [0, warpValue(0.9)], raw: 0.9, runId: "run-1" } }));
    expect(onPointClick).toHaveBeenCalledWith("run-1");
    // 阈值线等无 runId 的点击 → 不回调（silent 之外的防御）
    onPointClick.mockClear();
    clickHandlers.forEach((cb) => cb({ data: { value: [0, warpValue(0.87)], raw: 0.87 } }));
    clickHandlers.forEach((cb) => cb({ componentType: "markLine" }));
    expect(onPointClick).not.toHaveBeenCalled();
  });

  it("re-setOption when points change (merge mode keeps chart state)", () => {
    const { rerender } = render(
      <EvalTrendChart points={POINTS} baseline={BASELINE} labels={LABELS} />,
    );
    const before = echartsMock.setOptionCalls.length;
    const next = [...POINTS, point({ ts: "2026-08-21T09:00:00+00:00", run_id: "run-2" })];
    rerender(<EvalTrendChart points={next} baseline={BASELINE} labels={LABELS} />);
    expect(echartsMock.setOptionCalls.length).toBeGreaterThan(before);
    const option = lastOption();
    const recall = option.series.find((s) => s.name === "Recall@k");
    expect(recall?.data).toHaveLength(2);
    expect(recall?.data?.[1]?.runId).toBe("run-2");
  });

  it("datazoom patches showSymbol by visible run count and reports the span preset (contract v4)", () => {
    const onSpanChange = rs.fn();
    render(
      <EvalTrendChart points={POINTS} baseline={BASELINE} labels={LABELS} onSpanChange={onSpanChange} />,
    );
    const zoomHandlers = echartsMock.handlers.get("datazoom") ?? [];
    expect(zoomHandlers.length).toBeGreaterThan(0);

    // 单点：可见 1 ≤80 → 出符号点；跨度 0 → day 档上抛
    zoomHandlers.forEach((cb) => cb({}));
    const patch = echartsMock.setOptionCalls.at(-1)?.option as { series: { showSymbol: boolean }[] };
    expect(patch.series.every((s) => s.showSymbol === true)).toBe(true);
    expect(onSpanChange).toHaveBeenCalledWith("day");
  });

  it("dense visible runs hide symbols (zoomed-out trend tier)", () => {
    // 100 个 run 点：全窗可见 100 > 80 → 隐符号只留线
    const dense = Array.from({ length: 100 }, (_, i) =>
      point({ ts: `2026-05-${String((i % 28) + 1).padStart(2, "0")}T${String(i % 24).padStart(2, "0")}:00:00+00:00`, run_id: `run-${i}` }),
    );
    render(<EvalTrendChart points={dense} baseline={BASELINE} labels={LABELS} />);
    const zoomHandlers = echartsMock.handlers.get("datazoom") ?? [];
    zoomHandlers.forEach((cb) => cb({}));
    const patch = echartsMock.setOptionCalls.at(-1)?.option as { series: { showSymbol: boolean }[] };
    expect(patch.series.every((s) => s.showSymbol === false)).toBe(true);
  });

  it("spanRequest click applies the preset index window via dataZoom startValue/endValue", () => {
    // 三日点集：day 档 cutoff = 末点(08-22 10:00)−24h = 08-21 10:00 → start=1；
    // end = 2 + max(0.5, 1×0.02) = 2.5
    const threeDays = [
      point(),
      point({ ts: "2026-08-21T11:00:00+00:00", run_id: "run-2" }),
      point({ ts: "2026-08-22T10:00:00+00:00", run_id: "run-3" }),
    ];
    render(
      <EvalTrendChart
        points={threeDays}
        baseline={BASELINE}
        labels={LABELS}
        spanRequest={{ preset: "day", nonce: 1 }}
      />,
    );
    const zoomCall = [...echartsMock.setOptionCalls]
      .reverse()
      .find((c) => Array.isArray((c.option as { dataZoom?: unknown[] }).dataZoom));
    expect(zoomCall).toBeTruthy();
    const dz = (zoomCall!.option as { dataZoom: { startValue: number; endValue: number }[] }).dataZoom[0]!;
    // 索引窗（contract v5）：start = 24h 内首个索引，end 留右缘索引边距
    expect(dz.startValue).toBe(1);
    expect(dz.endValue).toBeCloseTo(2.5, 5);
  });
});
