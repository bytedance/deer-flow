"use client";

import type { ECharts } from "echarts";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { useCallback, useRef } from "react";

import { addChartCapture } from "@/core/genui/chart-screenshots";
import { echarts } from "@/lib/echarts-init";

interface EChartBlockProps {
  block: {
    props: {
      option: Record<string, unknown>;
      height?: number;
      theme?: string;
      loading?: boolean;
    };
    block_id?: string;
    metadata?: Record<string, unknown>;
  };
  threadId?: string;
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

export default function EChartBlock({ block, threadId }: EChartBlockProps) {
  const { props } = block;
  const { option, height = 400, theme = "industrial", loading = false } = props;
  const capturedRef = useRef(false);

  const chartTitle = extractTitle(option);

  const handleChartReady = useCallback(
    (instance: ECharts) => {
      if (capturedRef.current || !threadId) return;
      capturedRef.current = true;

      setTimeout(() => {
        try {
          const dataUrl = instance.getDataURL({
            type: "png",
            pixelRatio: 2,
            backgroundColor: "#fff",
          });
          if (!dataUrl?.startsWith("data:")) return;
          const filename = `chart_${block.block_id ?? Date.now()}.png`;
          addChartCapture(threadId, dataUrl, filename);
        } catch {
          // Capture is best-effort; don't break the UI
        }
      }, 800);
    },
    [threadId, block.block_id],
  );

  return (
    <div className="rounded-lg border bg-card p-4" role="img" aria-label={chartTitle ?? "ECharts visualization"}>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: `${height}px`, width: "100%" }}
        theme={theme === "default" ? "industrial" : theme}
        showLoading={loading}
        notMerge={true}
        lazyUpdate={true}
        onChartReady={handleChartReady}
      />
    </div>
  );
}
