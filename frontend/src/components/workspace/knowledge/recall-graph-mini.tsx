"use client";

/**
 * 检索测试·图谱路·实体视图（2026-09-05）：把当次召回的实体/关系渲染为力导向
 * 关系图（echarts graph 系列，与知识图谱 tab 同源；节点色 typeColor 按 type
 * 稳定取色）。与图谱 tab 大图的差异：数据仅当次召回命中子图、无 LOD/叠加/
 * 搜索居中；roam 缩放平移、节点可拖；节点 tooltip 带 description，边标签与
 * tooltip 带关系名。echarts init 防御性 try/catch——无 canvas 环境（jsdom）
 * 降级空容器，单测经模块 mock 覆盖渲染语义。
 */
import { GraphChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import type {
  RecallGraphEntity,
  RecallGraphRelation,
} from "@/core/knowledge/types";

import { widenRoamPointerChecker } from "./graph-canvas";
import { labelTierForZoom, type LabelTier, typeColor } from "./graph-utils";

echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

/** 当前是否暗色主题（next-themes 在 <html> 上挂 .dark class）。 */
function isDarkTheme(): boolean {
  return (
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("dark")
  );
}

/** 墨色：浅色主题用深灰，暗色主题翻成亮灰（边标签等装饰元素）。 */
function ink(alpha: number, dark: boolean): string {
  return dark ? `rgba(235,238,245,${alpha})` : `rgba(60,60,60,${alpha})`;
}

type MiniTooltipParams = {
  dataType?: "node" | "edge";
  name?: string;
  data?: {
    description?: string;
    value?: string;
    source?: string;
    target?: string;
  };
};

export function RecallGraphMini({
  entities,
  relations,
}: {
  entities: readonly RecallGraphEntity[];
  relations: readonly RecallGraphRelation[];
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  // 标签档位（2026-09-05 两层）：缩到 LABEL_ZOOM_HIDE_BELOW 以下隐藏名称
  // （同知识图谱 tab 配方，formatter 实现不碰 data）；实体数少不做合并/
  // 中档，略微遮挡可接受以显更多内容；hover emphasis 仍显单个名称。
  const labelTierRef = useRef<LabelTier>("full");

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let chart: echarts.ECharts;
    try {
      chart = echarts.init(host);
    } catch {
      return; // 无 canvas 环境（jsdom 等）降级空容器
    }
    chartRef.current = chart;
    // 全画布漫游（2026-09-05，复用图谱 tab 2026-08-20 圈外拖拽修复）：echarts
    // 默认把 roam pointerChecker 限在图内容包围盒内——空白区不能平移/缩放；
    // 强制恒 true 只放开空白区（节点拖拽由 _mousedownHandler 独立保护）。
    // 注意 echarts 每次 render 重设 checker，必须在 rendered 后重新覆盖。
    widenRoamPointerChecker(chart);
    chart.on("rendered", () => widenRoamPointerChecker(chart));
    // 缩放监听（同 graph-canvas）：zoom 从 option 读（roam 平移也触发本事件，
    // 事件参数不可靠）；跨档才 setOption 换 formatter，同档零成本短路。
    chart.on("graphRoam", () => {
      const seriesOptions = chart.getOption().series as
        | Array<{ zoom?: number }>
        | undefined;
      const zoom =
        typeof seriesOptions?.[0]?.zoom === "number"
          ? seriesOptions[0].zoom
          : 1;
      const tier = labelTierForZoom(zoom);
      if (tier === labelTierRef.current) return;
      labelTierRef.current = tier;
      chart.setOption({
        series: [
          {
            label: {
              show: true,
              formatter: (params: { name?: string }) =>
                tier === "hidden" ? "" : (params.name ?? ""),
            },
            edgeLabel: {
              show: true,
              formatter: (params: { data?: { value?: string } }) =>
                tier === "hidden" ? "" : (params.data?.value ?? ""),
            },
          },
        ],
      });
    });
    const observer = new ResizeObserver(() => {
      chart.resize();
      // resize 触发渲染 → 重设 checker，补覆盖（同 graph-canvas）。
      widenRoamPointerChecker(chart);
    });
    observer.observe(host);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const dark = isDarkTheme();
    // notMerge 重建后 zoom 回 1，标签档位同步复位（同 graph-canvas 先例）。
    labelTierRef.current = "full";
    // 关系端点可能含实体集外的名字（impl 只回 seen 子集）——悬空边不渲染。
    const names = new Set(entities.map((entity) => entity.name));
    const data = entities.map((entity) => ({
      name: entity.name,
      symbolSize: 16,
      itemStyle: { color: typeColor(entity.type) },
      description: entity.description,
    }));
    const links = relations
      .filter(
        (relation) =>
          names.has(relation.source) && names.has(relation.target),
      )
      .map((relation) => ({
        source: relation.source,
        target: relation.target,
        value: relation.relation,
      }));
    chart.setOption(
      {
        tooltip: {
          formatter: (params: MiniTooltipParams) => {
            if (params.dataType === "edge") {
              return `${params.data?.source} —${params.data?.value}→ ${params.data?.target}`;
            }
            return `<b>${params.name}</b><br/>${params.data?.description ?? ""}`;
          },
        },
        series: [
          {
            type: "graph",
            layout: "force",
            roam: true,
            draggable: true,
            data,
            links,
            label: {
              show: true,
              position: "right",
              fontSize: 10,
              color: ink(0.85, dark),
              // 分级经 formatter（读 labelTierRef）：缩略态返回空串隐藏名称。
              formatter: (params: { name?: string }) =>
                labelTierRef.current === "hidden" ? "" : (params.name ?? ""),
            },
            emphasis: {
              focus: "adjacency",
              // 隐藏档下 hover 仍显单个名称（同图谱 tab 语义）。
              label: {
                show: true,
                formatter: (params: { name?: string }) => params.name ?? "",
              },
            },
            edgeLabel: {
              show: true,
              fontSize: 9,
              color: ink(0.6, dark),
              // 关系名随标签档位联动隐藏（缩略态只留节点与边线）。
              formatter: (params: { data?: { value?: string } }) =>
                labelTierRef.current === "hidden"
                  ? ""
                  : (params.data?.value ?? ""),
            },
            lineStyle: { color: "source", curveness: 0.12, opacity: 0.7 },
            edgeSymbol: ["none", "arrow"],
            edgeSymbolSize: 6,
            force: { repulsion: 140, edgeLength: [60, 100], gravity: 0.1 },
          },
        ],
      },
      true,
    );
  }, [entities, relations]);

  return (
    <div
      className="h-full min-h-0 w-full"
      data-testid="recall-graph-mini"
      ref={hostRef}
    />
  );
}
