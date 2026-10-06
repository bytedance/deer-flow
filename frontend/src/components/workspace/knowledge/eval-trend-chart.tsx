"use client";

/**
 * 指标趋势画布（2026-08-24 spec §4，plan Task 3）：echarts 手写适配层。
 * 经 next/dynamic(ssr:false) 由 eval-tab 懒加载——不进首屏 chunk（对齐
 * vector-tab 挂载 vector-canvas 的先例）。
 * 纯渲染组件：不 fetch、不调 useI18n——数据与文案（labels）经 props 注入；
 * option 组装在 eval-trend-chart.utils.ts 纯函数（jsdom 可测，graph-utils 先例）。
 * jsdom 不可运行 echarts，DOM 测试中 mock echarts/core 适配层。
 */
import { LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import type { TrendChartLabels, TrendPoint, TrendResponse } from "@/core/knowledge/types";

import { buildChartOption, formatAxisTime, presetToIndexWindow, resolveShowSymbol, spanToPreset, type SpanPreset, type SpanRequest } from "./eval-trend-chart.utils";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

export interface EvalTrendChartProps {
  points: TrendPoint[];
  baseline: TrendResponse["baseline"];
  /** i18n 文案包（eval-tab 注入；保持本组件纯渲染）。 */
  labels: TrendChartLabels;
  onPointClick?: (runId: string) => void;
  /** picker 选中的稀疏指标键（会话级，eval-tab 持有）——条件并入 series。 */
  pickerSelected?: readonly string[];
  /** 图例开关回流态（echarts legendselectchanged 经 onLegendChange 上抛后回注）。 */
  legendSelected?: Record<string, boolean>;
  /** 图例开关变化回调——驱动 eval-tab 更新 legendSelected → y 轴按可见集自适应。 */
  onLegendChange?: (selected: Record<string, boolean>) => void;
  /** 视窗预设点击请求（contract v4）：nonce 区分同档重复点击，identity 变化才 apply 窗口。 */
  spanRequest?: SpanRequest | null;
  /** 滚轮缩放跨度回算预设上抛——eval-tab 按钮高亮（密度指示器）。 */
  onSpanChange?: (preset: SpanPreset) => void;
}

/** 当前是否暗色主题（next-themes 在 <html> 上挂 .dark class）。 */
function isDarkTheme(): boolean {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark");
}

export default function EvalTrendChart({
  points,
  baseline,
  labels,
  onPointClick,
  pickerSelected,
  legendSelected,
  onLegendChange,
  spanRequest,
  onSpanChange,
}: EvalTrendChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.EChartsType | null>(null);
  // 回调经 ref 穿透，避免 identity 变化触发 setOption（vector-canvas 先例）。
  const clickRef = useRef(onPointClick);
  clickRef.current = onPointClick;
  const legendChangeRef = useRef(onLegendChange);
  legendChangeRef.current = onLegendChange;
  const spanChangeRef = useRef(onSpanChange);
  spanChangeRef.current = onSpanChange;
  // run 级点 ts（ms）升序：密度档与视窗预设共用（数据 effect 同步）。
  const tsRef = useRef<number[]>([]);
  // 当前密度档（contract v5）：横轴标签格式活读（day 出 HH:mm、其余 MM-DD）。
  const presetRef = useRef<SpanPreset>("month");
  // 密度档同步函数：init effect 注册，数据/主题/视窗 effect 重建后调用。
  const applyDensityRef = useRef<() => void>(() => undefined);
  // 主题重建读取最新 props：init effect 只跑一次，闭包捕获会过期。
  const argsRef = useRef({ points, baseline, labels, pickerSelected, legendSelected });
  argsRef.current = { points, baseline, labels, pickerSelected, legendSelected };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = echarts.init(container);
    chartRef.current = chart;
    chart.on("click", (params) => {
      // 从 datum 取 runId——不依赖 dataIndex（多 series / markLine 下索引不对齐）。
      const runId = (params as { data?: { runId?: string } }).data?.runId;
      if (runId) clickRef.current?.(runId);
    });
    // 图例开关回流：上抛最新 selected，eval-tab 更新 state → legendSelected prop 回注
    // → 数据更新 effect 重建 option（y 轴按可见集自适应，spec §4.6）。
    chart.on("legendselectchanged", (params) => {
      legendChangeRef.current?.((params as { selected: Record<string, boolean> }).selected);
    });
    // 缩放密度档（contract v5 索引域）：dataZoom 可见窗索引 → 可见 run 数 →
    // 逐 series patch showSymbol（放大出每次测试点 / 缩小隐点看总体趋势；
    // 隐点不降采样，hover 仍命中真实 run）；跨度回算预设上抛作按钮密度
    // 指示，并同步 presetRef 供横轴标签格式活读。只 patch series 不整表重建。
    const applyDensity = () => {
      const opt = chart.getOption() as {
        dataZoom?: Array<{ startValue?: number; endValue?: number }>;
        series?: unknown[];
      };
      const dz = opt.dataZoom?.[0];
      const tsList = tsRef.current;
      if (!dz || tsList.length === 0) return;
      const last = tsList.length - 1;
      const clampIdx = (n: number) => Math.min(last, Math.max(0, Math.round(n)));
      const lo = clampIdx(dz.startValue ?? 0);
      const hi = clampIdx(dz.endValue ?? last);
      const visible = hi - lo + 1;
      const showSymbol = resolveShowSymbol(visible);
      const preset = spanToPreset(tsList[hi]! - tsList[lo]!);
      presetRef.current = preset;
      chart.setOption({ series: (opt.series ?? []).map(() => ({ showSymbol })) });
      spanChangeRef.current?.(preset);
    };
    applyDensityRef.current = applyDensity;
    chart.on("datazoom", applyDensity);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    // 主题切换（<html> .dark）→ 全量重建（轴/图例/tooltip 等装饰层主题感知）。
    const themeObserver = new MutationObserver(() => {
      chart.setOption(
        buildChartOption({
          ...argsRef.current,
          dark: isDarkTheme(),
          formatAxisTime: (ts) => formatAxisTime(ts, presetRef.current),
        }),
        { notMerge: true },
      );
      applyDensity();
    });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => {
      observer.disconnect();
      themeObserver.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
    // init 只跑一次；数据更新走下方 merge effect。
  }, []);

  useEffect(() => {
    tsRef.current = points.map((p) => new Date(p.ts).getTime()).sort((a, b) => a - b);
    chartRef.current?.setOption(
      buildChartOption({
        points,
        baseline,
        labels,
        dark: isDarkTheme(),
        pickerSelected,
        legendSelected,
        formatAxisTime: (ts) => formatAxisTime(ts, presetRef.current),
      }),
      { notMerge: false },
    );
    applyDensityRef.current();
  }, [points, baseline, labels, pickerSelected, legendSelected]);

  // 视窗预设（contract v5 索引窗）：仅点击请求（nonce）到达时 apply 窗口——
  // 滚轮回算的高亮不回灌窗口，避免与用户缩放抢控制权；右缘索引边距防末点贴边。
  useEffect(() => {
    const chart = chartRef.current;
    const tsList = tsRef.current;
    if (!chart || !spanRequest || tsList.length === 0) return;
    const win = presetToIndexWindow(tsList, spanRequest.preset);
    presetRef.current = spanRequest.preset;
    chart.setOption({ dataZoom: [{ startValue: win.start, endValue: win.end }] });
    applyDensityRef.current();
  }, [spanRequest]);

  return <div className="h-[280px] w-full" data-testid="eval-trend-chart" ref={containerRef} />;
}
