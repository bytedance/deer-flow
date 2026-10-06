"use client";

/**
 * 知识图谱画布（2026-08-19 spec §5/§6）：echarts `graph` 系列力导向渲染
 * 实体/关系。纯编码函数在 ./graph-utils（jsdom 可直测）；本文件只做
 * echarts 适配：init / setOption / resize / click·dblclick 事件 / 搜索居中。
 */
import { GraphChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import type { GraphRetrievalTrace, KnowledgeGraphCommunity, KnowledgeGraphEdge, KnowledgeGraphNode } from "@/core/knowledge/types";

import {
  buildAdjacencyMap,
  buildTieredSeries,
  type GraphColorBy,
  type GraphDatum,
  type GraphTooltipParams,
  graphTooltipFormatter,
  GRAPH_FOCUS_ZOOM,
  initialZoomForGraph,
  type LabelTier,
  labelTextForTier,
  labelTierForZoom,
  type RenderTier,
  renderTierForZoom,
} from "./graph-utils";

// 纯函数与类型的单测入口对齐 vector-canvas 先例——从 canvas 模块 re-export，
// 测试 import 路径保持 "@/components/workspace/knowledge/graph-canvas"。
export {
  buildAdjacencyMap,
  buildCommunityColorMap,
  buildGraphData,
  buildGraphLinks,
  buildGraphSeries,
  buildTieredSeries,
  COMMUNITY_PALETTE,
  filterNeighborhood,
  fnv1aHash,
  GRAPH_EXPANSION_BORDER_COLOR,
  GRAPH_FOCUS_ZOOM,
  GRAPH_HIT_BORDER_COLOR,
  GRAPH_HOVER_BORDER_COLOR,
  GRAPH_PATH_COLOR,
  type GraphColorBy,
  graphTooltipFormatter,
  IMPORTANT_MENTION_MIN,
  isNodeRenderedAtZoom,
  LABEL_ZOOM_FULL_ABOVE,
  LABEL_ZOOM_HIDE_BELOW,
  type LabelTier,
  labelTextForTier,
  labelTierForZoom,
  initialZoomForGraph,
  LOD_FULL_HARD_LIMIT,
  LOD_HUB_NODE_BUDGET,
  LOD_MIN_NODES,
  matchEntityNames,
  nodeSymbolSize,
  type RenderTier,
  renderTierForZoom,
  typeColor,
  tierNodeIds,
} from "./graph-utils";

echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

/** 当前是否暗色主题（next-themes 在 <html> 上挂 .dark class）。 */
function isDarkTheme(): boolean {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark");
}

/** 墨色：浅色主题用深灰，暗色主题翻成亮灰（边/标签等装饰元素）。 */
function ink(alpha: number, dark: boolean): string {
  return dark ? `rgba(235,238,245,${alpha})` : `rgba(60,60,60,${alpha})`;
}

/** LOD 跨档过渡动画时长（plan Task 7b：淡出/淡入 300ms 防闪）。 */
const TIER_TRANSITION_MS = 300;
/** 搜索定位的力导向稳定窗：布局动画进行中坐标仍会变，实测 500ms 后足够稳定。 */
const FOCUS_SETTLE_MS = 500;

/** 跨档重建 series 所需的当前数据（= dataRef.current 的形状）。 */
interface TierInput {
  nodes: readonly KnowledgeGraphNode[];
  edges: readonly KnowledgeGraphEdge[];
  communities: readonly KnowledgeGraphCommunity[];
  colorBy: GraphColorBy;
}

/**
 * 跨档重建 series（merge 语义）：data/links 是整体替换，datum 完整携带
 * itemStyle/symbolSize——绝不能只 set 部分字段的 series.data（会丢样式，全图
 * 节点回落默认色板蓝）。roam 跨档与搜索升档共用同一重建路径。
 */
function rebuildSeriesAtTier(chart: echarts.ECharts, tier: RenderTier, input: TierInput, overlay: GraphRetrievalTrace | null): void {
  const [nextSeries] = buildTieredSeries(input.nodes, input.edges, input.communities, tier, input.colorBy, overlay);
  chart.setOption({
    series: [
      {
        data: nextSeries.data,
        links: nextSeries.links,
        edgeSymbol: nextSeries.edgeSymbol,
        animationDurationUpdate: TIER_TRANSITION_MS,
      },
    ],
  });
}

/** 标签档位落地：formatter 捕获 tier 于闭包（labelTierRef 由调用方同步去重）。 */
function applyLabelTier(chart: echarts.ECharts, tier: LabelTier): void {
  chart.setOption({
    series: [
      {
        label: {
          show: true,
          formatter: (params: { data?: unknown }) => {
            const data = params.data as GraphDatum | undefined;
            return labelTextForTier(data?.node, tier, data?.name ?? "");
          },
        },
      },
    ],
  });
}

/**
 * 当前已渲染的 series 数据句柄（echarts 内部 API：类型标私有但运行时可用）。
 * 按名查下标与读节点 layout 坐标都没有公开替代（convertToPixel 不支持 graph
 * 系列的 roam 坐标系）。
 */
interface SeriesDataHandle {
  indexOfName(name: string): number;
  getItemLayout(index: number): [number, number] | undefined;
}

function seriesDataOf(chart: echarts.ECharts): SeriesDataHandle | undefined {
  const internals = chart as unknown as {
    getModel(): { getSeriesByIndex(index: number): { getData(): SeriesDataHandle } | undefined };
  };
  return internals.getModel().getSeriesByIndex(0)?.getData();
}

export interface GraphCanvasProps {
  nodes: readonly KnowledgeGraphNode[];
  edges: readonly KnowledgeGraphEdge[];
  /** Task 7b LOD：社区汇总（hub 层 TopN 枢纽数据源）。 */
  communities: readonly KnowledgeGraphCommunity[];
  /** 着色模式（spec §6）：默认按社区，可切按类型。 */
  colorBy: GraphColorBy;
  /** 搜索定位：命中的节点 id（居中 + 高亮）；null = 无定位请求。 */
  focusNode: string | null;
  /** P4 检索路径叠加（spec §7）：种子/扩展/证据三层染色；null = 无叠加。 */
  overlay?: GraphRetrievalTrace | null;
  /** 单击节点 → 实体钻取（抽屉由 graph-tab 渲染）。 */
  onNodeClick: (node: KnowledgeGraphNode) => void;
  /** 双击节点 → 进入局部图模式（spec §6，对齐 Obsidian）。 */
  onNodeDblClick: (node: KnowledgeGraphNode) => void;
  /** LOD 渲染档位变化上报（tab 层 guide 引导提示用）。 */
  onRenderTierChange?: (tier: RenderTier) => void;
}

/**
 * 放宽 graph roam 的手势范围到全画布（2026-08-20 圈外拖拽修复）。
 *
 * 根因：echarts GraphView._updateController 把 RoamController.pointerChecker 限定为
 * 「图内容包围盒内」，空白区域（节点团外）不触发平移/缩放。但节点拖拽已被独立保护
 * ——_mousedownHandler 会先检查 e.target 是否 draggable（是则提前返回），所以强制
 * checker 恒 true 只会让空白区域可平移，不会破坏节点拖拽。
 *
 * 注意：echarts 每次 render 会重设 checker，必须在 chart.on('rendered') 里重新覆盖。
 */
export function widenRoamPointerChecker(chart: unknown): void {
  if (!chart || typeof chart !== "object") return;
  const internals = chart as {
    _chartsViews?: Array<{
      _controller?: { setPointerChecker(checker: () => boolean): void };
    }>;
  };
  if (!internals._chartsViews?.length) return;
  for (const view of internals._chartsViews) {
    view?._controller?.setPointerChecker(() => true);
  }
}

export default function GraphCanvas({ nodes, edges, communities, colorBy, focusNode, overlay, onNodeClick, onNodeDblClick, onRenderTierChange }: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  // 回调穿透 ref：数据刷新重建 option 时不需要重绑事件。
  const onNodeClickRef = useRef(onNodeClick);
  onNodeClickRef.current = onNodeClick;
  const onNodeDblClickRef = useRef(onNodeDblClick);
  onNodeDblClickRef.current = onNodeDblClick;
  const onRenderTierChangeRef = useRef(onRenderTierChange);
  onRenderTierChangeRef.current = onRenderTierChange;
  // 标签档位去重：graphRoam 在平移时也会触发（zoom 不变 → tier 不变 → 短路）。
  const labelTierRef = useRef<LabelTier>("full");
  // LOD 渲染档位（Task 7b）：初始 zoom 由 initialZoomForGraph 评估（大库 0.3 落 hub，
  // 小库门控 zoom=1 恒 full）；roam 跨档时 merge 重建 series。
  const renderTierRef = useRef<RenderTier>(renderTierForZoom(initialZoomForGraph(nodes.length), nodes.length));
  // overlay 穿透 ref：全量重建 effect 读取最新叠加但不以其为依赖（叠加单变更
  // 走下方 merge 更新，不重跑力导向布局——对齐向量空间「叠加系列槽位」教训）。
  const overlayRef = useRef(overlay ?? null);
  overlayRef.current = overlay ?? null;
  // roam handler（初始化时绑定一次）读最新数据的穿透 ref。
  const dataRef = useRef({ nodes, edges, communities, colorBy });
  dataRef.current = { nodes, edges, communities, colorBy };
  // 最近一次全量重建的输入指纹（引用对比）：overlay-only 变更才可走 merge 更新。
  const lastFullRebuildRef = useRef<{
    nodes: readonly KnowledgeGraphNode[];
    edges: readonly KnowledgeGraphEdge[];
    colorBy: GraphColorBy;
  } | null>(null);
  const appliedOverlayRef = useRef<GraphRetrievalTrace | null>(null);
  // hover 邻域提亮的邻接表：effect A 数据重建时刷新，事件 handler 经 ref 读最新值。
  const adjacencyRef = useRef<Map<string, string[]>>(new Map());

  // 初始化一次：事件绑定与尺寸观察。
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = echarts.init(container);
    chartRef.current = chart;

    const datumOf = (params: unknown): GraphDatum | null => {
      const p = params as { dataType?: string; data?: unknown };
      if (p.dataType !== "node") return null;
      return (p.data as GraphDatum | undefined) ?? null;
    };
    chart.on("click", (params) => {
      const datum = datumOf(params);
      if (!datum) return;
      if (datum.node) onNodeClickRef.current(datum.node);
    });
    chart.on("dblclick", (params) => {
      const datum = datumOf(params);
      if (!datum) return;
      if (datum.node) onNodeDblClickRef.current(datum.node);
    });

    // hover 邻域提亮（2026-08-20 加法高亮）：echarts focus:adjacency 只保证邻居
    // 「不被压暗」而非主动高亮（states.js：只有当前 hover 元素进 emphasis）——
    // 邻居提亮必须手动 dispatch highlight，让「当前节点+1 跳邻居」同走蓝描边。
    // 系列不配 focus/blur，其他元素全程 normal：纯加法，零闪烁。
    const dispatchNeighborhood = (params: unknown, action: "highlight" | "downplay") => {
      const p = params as { dataType?: string; name?: unknown };
      if (p.dataType !== "node" || typeof p.name !== "string") return;
      const names = [p.name, ...(adjacencyRef.current.get(p.name) ?? [])];
      chart.dispatchAction({ type: action, seriesIndex: 0, name: names });
    };
    chart.on("mouseover", (params) => dispatchNeighborhood(params, "highlight"));
    chart.on("mouseout", (params) => dispatchNeighborhood(params, "downplay"));
    // 鼠标直接甩出画布时兜底：downplay 无参=清除全部高亮（防滞留）。
    chart.on("globalout", () => {
      chart.dispatchAction({ type: "downplay", seriesIndex: 0 });
    });

    // 缩放监听（标签分级 2026-08-19 + LOD 渲染档位 2026-08-21 Task 7b）：
    // chart.on 注册的监听挂在实例上，setOption（含 notMerge）不会清除——
    // 只需初始化时绑一次。zoom 从 option 读（roam 平移也触发本事件，事件参数
    // 不可靠，以 option 中的当前 zoom 为准）。
    // 分级用 label.formatter 实现——绝不能 setOption 部分字段的 series.data
    // （整体替换语义会丢 itemStyle/symbolSize，全图节点回落默认色板蓝色）。
    chart.on("graphRoam", () => {
      const seriesOptions = chart.getOption().series as Array<{ zoom?: number }> | undefined;
      const zoom = typeof seriesOptions?.[0]?.zoom === "number" ? seriesOptions[0].zoom : 1;
      const current = dataRef.current;

      // LOD 渲染档位切换：跨档时 merge 重建 series（data/links 整体替换语义，
      // datum 完整携带 itemStyle/symbolSize），300ms 过渡动画；同档零成本短路。
      const nextRenderTier = renderTierForZoom(zoom, current.nodes.length);
      const tierChanged = nextRenderTier !== renderTierRef.current;
      if (tierChanged) {
        renderTierRef.current = nextRenderTier;
        onRenderTierChangeRef.current?.(nextRenderTier);
        rebuildSeriesAtTier(chart, nextRenderTier, current, overlayRef.current);
      }

      const tier = labelTierForZoom(zoom);
      if (!tierChanged && tier === labelTierRef.current) return;
      labelTierRef.current = tier;
      applyLabelTier(chart, tier);
    });

    const observer = new ResizeObserver(() => {
      chart.resize();
      // resize 触发渲染 → 重设 checker，补覆盖。
      widenRoamPointerChecker(chart);
    });
    observer.observe(container);

    // echarts 每次 render 会重设 checker 为包围盒模式——必须在 rendered 后重新覆盖，
    // 否则 resize/setOption 后圈外手势又静默失效。
    chart.on("rendered", () => {
      widenRoamPointerChecker(chart);
    });

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // 数据 → option。nodes/edges 来自 React Query（引用稳定），变化即整体重建
  // 布局（force 图节点集合变化后位置本就应重排，notMerge 语义对齐）。
  // 当前叠加经 overlayRef 参与重建——数据变了，叠加染色必须随新数据一起落地。
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const dark = isDarkTheme();
    const activeOverlay = overlayRef.current;
    // hover 邻域提亮的邻接表随数据重建刷新（mouseover handler 经 ref 读最新值）。
    adjacencyRef.current = buildAdjacencyMap(edges);
    // LOD 渲染档位（Task 7b）：初始 zoom=1 评估——小库门控恒 full；大库初始
    // 落在 all-full/guide（超 2000 熔断）。notMerge 重建后 roam 状态复位 zoom=1，
    // 与这里的初始评估自洽。
    const initialZoom = initialZoomForGraph(nodes.length);
    const tier = renderTierForZoom(initialZoom, nodes.length);
    renderTierRef.current = tier;
    onRenderTierChangeRef.current?.(tier);
    const [series] = buildTieredSeries(nodes, edges, communities, tier, colorBy, activeOverlay);
    // 数据重建后标签档位回到 full（notMerge 清掉了 roam 期间的档位覆盖），
    // 同步重置 ref——否则下次 roam 到同一档会因去重短路而丢失标签状态。
    labelTierRef.current = labelTierForZoom(initialZoom);
    chart.setOption(
      {
        tooltip: {
          trigger: "item",
          formatter: (params: unknown) => graphTooltipFormatter(params as GraphTooltipParams),
          backgroundColor: dark ? "rgba(30,32,36,0.92)" : "rgba(255,255,255,0.92)",
          borderWidth: 0,
          textStyle: { color: ink(0.85, dark), fontSize: 12 },
          extraCssText: "backdrop-filter: blur(6px); border-radius: 6px; padding: 6px 10px;",
        },
        series: [
          {
            ...series,
            // 初始 zoom：大库最缩略档（0.3），小库默认 1。
            zoom: initialZoom,
            // opacity 必须显式钉死为 1：echarts graph 默认 lineStyle.opacity 0.5，
            // 若继承它，blur.lineStyle.opacity=1（零淡化意图）反而把 hover 时的
            // 非邻接边从 0.5 提亮到 1——「全局边高亮」事故根因（2026-08-20 排查）。
            lineStyle: { color: ink(0.35, dark), width: 1, opacity: 1 },
            label: {
              ...series.label,
              color: ink(0.75, dark),
              formatter: (params: { data?: unknown }) => {
                const data = params.data as GraphDatum | undefined;
                return labelTextForTier(data?.node, labelTierRef.current, data?.name ?? "");
              },
            },
          },
        ],
      },
      { notMerge: true },
    );
    // notMerge 重建会重设 checker——立即覆盖（rendered 事件兜底之外的防御）。
    widenRoamPointerChecker(chart);
    lastFullRebuildRef.current = { nodes, edges, colorBy };
    appliedOverlayRef.current = activeOverlay;
  }, [nodes, edges, communities, colorBy]);

  // P4 叠加单变更（spec §7）：只替换 series 的 data/links（merge 模式），
  // 保留力导向布局位置与视口——全量重建会让节点重新模拟、用户视角丢失。
  // data/links 都是整体替换语义（完整 datum 携带 itemStyle/symbolSize，
  // 不会重蹈 Task 4 部分字段丢失的坑）。
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const last = lastFullRebuildRef.current;
    // nodes/edges 引用恒非空——last 缺失（未全量重建过）时 ?. 求值为 undefined ≠ nodes，恒走 return。
    if (last?.nodes !== nodes || last.edges !== edges || last.colorBy !== colorBy) {
      return; // 数据未就绪或刚变更——等全量重建 effect 处理（它经 overlayRef 读最新值）。
    }
    const next = overlay ?? null;
    if (appliedOverlayRef.current === next) return;
    appliedOverlayRef.current = next;
    // LOD：叠加变更按当前渲染档位重建——cluster 层命中社区上卷（红描边），
    // 实体层照旧红/金描边（buildTieredSeries 内部分流）。
    const [nextSeries] = buildTieredSeries(nodes, edges, communities, renderTierRef.current, colorBy, next);
    chart.setOption({ series: [{ data: nextSeries.data, links: nextSeries.links }] });
  }, [overlay, nodes, edges, communities, colorBy]);

  // 搜索定位（spec §6 P3 + 2026-09-08 LOD 修复）：命中节点 → 视图中心平移到该
  // 节点 + 高亮。center 语义 = roam 视图中心对应的 layout 坐标（echarts graph 原生
  // 支持）；节点 layout 坐标从 series data 的 getItemLayout 读取（force 布局完成后有值）。
  //
  // 两处旧缺陷（缩略态搜索静默无反应的根因）：
  // 1. 下标取自全量 nodes 数组，而 data 是当前 LOD 档的子集——两下标不同空间：
  //    越界时 getItemLayout 返 undefined 静默 return，落在子集长度内时更会静默居中
  //    到不相干的实体。现改为在已渲染数据里按名解析（datum.name = 实体 id）。
  // 2. 定位把 zoom 推到 GRAPH_FOCUS_ZOOM，但 setOption 改 zoom 不触发 graphRoam →
  //    档位状态与真实 zoom 脱钩，且缩略档上命中实体根本没被渲染。现搜索一律
  //    升档到定位 zoom 对应的档位（plan Task 7b：任何层级下检索命中都可见）。
  // 升档后仍不在子集（guide 熔断）时无坐标可居中——这一情形已由 tab 层改走局部图裁剪兜底。
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !focusNode) return;
    let cancelled = false;
    const timers: number[] = [];

    const applyFocus = () => {
      if (cancelled) return;
      const data = seriesDataOf(chart);
      if (!data) return;
      const index = data.indexOfName(focusNode);
      if (index < 0) return; // 不在已渲染子集内（guide 熔断）——无物可居中
      const layout = data.getItemLayout(index);
      if (!layout) return; // 布局未完成，没有坐标可读
      chart.setOption({ series: [{ center: [layout[0], layout[1]], zoom: GRAPH_FOCUS_ZOOM }] });
      chart.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: index });
    };

    // 力导向布局动画进行中坐标仍会变——等一个短暂稳定窗再居中（启动动画期的
    // 居中会被后续模拟推开）。
    timers.push(
      window.setTimeout(() => {
        if (cancelled) return;
        const nextTier = renderTierForZoom(GRAPH_FOCUS_ZOOM, nodes.length);
        if (nextTier === renderTierRef.current) {
          applyFocus();
          return;
        }
        // 升档：重建 series 后档位/标签状态必须同步（程序化 zoom 不发 graphRoam），
        // 否则后续 roam 的跨档判定与 guide 引导提示都拿到陈旧档位。
        renderTierRef.current = nextTier;
        onRenderTierChangeRef.current?.(nextTier);
        labelTierRef.current = labelTierForZoom(GRAPH_FOCUS_ZOOM);
        rebuildSeriesAtTier(chart, nextTier, dataRef.current, overlayRef.current);
        applyLabelTier(chart, labelTierRef.current);
        // 重建重启了力导向模拟 → 再等一个稳定窗才读坐标。
        timers.push(window.setTimeout(applyFocus, FOCUS_SETTLE_MS));
      }, FOCUS_SETTLE_MS),
    );

    return () => {
      cancelled = true;
      for (const timer of timers) window.clearTimeout(timer);
      chart.dispatchAction({ type: "downplay", seriesIndex: 0 });
    };
  }, [focusNode, nodes]);

  return <div ref={containerRef} className="h-full w-full" data-testid="graph-canvas" />;
}
