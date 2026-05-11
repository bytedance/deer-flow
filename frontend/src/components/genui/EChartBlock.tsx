"use client";

import ReactEChartsCore from "echarts-for-react/lib/core";

import { echarts } from "@/lib/echarts-init";

interface EChartBlockProps {
  block: {
    props: {
      option: Record<string, unknown>;
      height?: number;
      theme?: string;
      loading?: boolean;
    };
  };
}

function extractTitle(option: Record<string, unknown>): string | undefined {
  const title = option?.title;
  if (Array.isArray(title)) {
    return (title[0] as { text?: string } | undefined)?.text;
  }
  if (typeof title === "object" && title !== null) {
    return (title as { text?: string }).text;
  }
  return undefined;
}

export default function EChartBlock({ block }: EChartBlockProps) {
  const { props } = block;
  const { option, height = 400, theme = "default", loading = false } = props;

  const chartTitle = extractTitle(option);

  return (
    <div className="rounded-lg border bg-card p-4" role="img" aria-label={chartTitle ?? "ECharts visualization"}>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: `${height}px`, width: "100%" }}
        theme={theme === "default" ? undefined : theme}
        showLoading={loading}
        notMerge={true}
        lazyUpdate={true}
      />
    </div>
  );
}
