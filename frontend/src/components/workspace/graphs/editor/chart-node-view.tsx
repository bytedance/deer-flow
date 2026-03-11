"use client";

import { type NodeViewProps, NodeViewWrapper } from "@tiptap/react";
import * as echarts from "echarts";
import {
  AlertTriangleIcon,
  EditIcon,
  SparklesIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { getAPIClient } from "@/core/api";
import { cn } from "@/lib/utils";

import {
  fixDatasetLabels,
  fixDatasetTooltip,
  sanitizeFormatters,
  stripExplicitColors,
} from "../chart-sanitizers";
import {
  type DashboardTheme,
  buildEChartsTheme,
  getDashboardTheme,
  subscribeDashboardTheme,
} from "../chart-themes";
import { emitDrillDown } from "../drill-down-events";

const registeredThemes = new Set<string>();

function useTheme() {
  return useSyncExternalStore(subscribeDashboardTheme, getDashboardTheme, getDashboardTheme);
}

function injectGradients(
  opt: Record<string, unknown>,
  theme: DashboardTheme,
): Record<string, unknown> {
  const series = opt.series;
  if (!Array.isArray(series)) return opt;

  const enhanced = series.map((s: Record<string, unknown>, i: number) => {
    const type = s.type as string;
    const color = theme.colors[i % theme.colors.length]!;

    if (type === "line" && !s.areaStyle) {
      return {
        ...s,
        lineStyle: { ...(s.lineStyle as object ?? {}), width: 2.5 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: color + "30" },
            { offset: 1, color: color + "05" },
          ]),
        },
        smooth: 0.4,
        symbol: "none",
        emphasis: {
          focus: "series",
          itemStyle: { shadowBlur: 10, shadowColor: color + "40" },
        },
      };
    }

    if (type === "bar") {
      return {
        ...s,
        itemStyle: {
          ...(s.itemStyle as object ?? {}),
          borderRadius: [6, 6, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color },
            { offset: 1, color: color + "99" },
          ]),
        },
        emphasis: {
          itemStyle: { shadowBlur: 12, shadowColor: color + "30" },
        },
      };
    }

    if (type === "pie") {
      return {
        ...s,
        itemStyle: {
          ...(s.itemStyle as object ?? {}),
          borderRadius: 6,
          borderColor: "#fff",
          borderWidth: 2,
        },
        emphasis: {
          itemStyle: { shadowBlur: 20, shadowColor: "rgba(0,0,0,0.12)" },
          scaleSize: 8,
        },
      };
    }

    // Apply default annotation styling for markPoint/markLine
    const result = { ...s } as Record<string, unknown>;
    if (result.markPoint && typeof result.markPoint === "object") {
      const mp = result.markPoint as Record<string, unknown>;
      result.markPoint = {
        ...mp,
        itemStyle: { color: "#ef4444", ...(mp.itemStyle as object ?? {}) },
        label: { fontSize: 10, color: "#fff", ...(mp.label as object ?? {}) },
      };
    }
    if (result.markLine && typeof result.markLine === "object") {
      const ml = result.markLine as Record<string, unknown>;
      result.markLine = {
        ...ml,
        lineStyle: { type: "dashed", color: "#ef4444", ...(ml.lineStyle as object ?? {}) },
        label: { fontSize: 10, ...(ml.label as object ?? {}) },
      };
    }

    return result;
  });

  return { ...opt, series: enhanced };
}

export function ChartNodeView({ node, selected, editor, getPos: _getPos, updateAttributes }: NodeViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [hovered, setHovered] = useState(false);
  const [aiEditOpen, setAiEditOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const promptInputRef = useRef<HTMLInputElement>(null);
  const theme = useTheme();

  const { title, option } = node.attrs;

  // Count annotations (markPoint/markLine) in series
  const annotationCount = useMemo(() => {
    const series = option?.series;
    if (!Array.isArray(series)) return 0;
    let count = 0;
    for (const s of series) {
      const mp = (s as Record<string, unknown>).markPoint as { data?: unknown[] } | undefined;
      const ml = (s as Record<string, unknown>).markLine as { data?: unknown[] } | undefined;
      if (mp?.data) count += mp.data.length;
      if (ml?.data) count += ml.data.length;
    }
    return count;
  }, [option]);

  useEffect(() => {
    const themeName = `dashboard-${theme.id}`;
    if (!registeredThemes.has(themeName)) {
      echarts.registerTheme(themeName, buildEChartsTheme(theme));
      registeredThemes.add(themeName);
    }

    if (!containerRef.current) return;

    if (chartRef.current) {
      chartRef.current.dispose();
    }

    const instance = echarts.init(containerRef.current, themeName);
    chartRef.current = instance;

    let cleanOption = sanitizeFormatters(option) as Record<string, unknown>;
    cleanOption = fixDatasetTooltip(cleanOption);
    cleanOption = fixDatasetLabels(cleanOption);
    cleanOption = stripExplicitColors(cleanOption);
    cleanOption = injectGradients(cleanOption, theme);

    cleanOption = {
      ...cleanOption,
      animation: true,
      animationDuration: 800,
      animationEasing: "cubicInOut",
      animationDurationUpdate: 500,
    };

    instance.setOption(cleanOption as echarts.EChartsOption);

    // Drill-down: emit event on chart click
    instance.on("click", (params) => {
      const seriesOpt = cleanOption.series;
      const seriesArr = Array.isArray(seriesOpt) ? seriesOpt : [];
      const clickedSeries = seriesArr[params.seriesIndex ?? 0] as Record<string, unknown> | undefined;
      const rawName = params.seriesName ?? clickedSeries?.name;
      const seriesName = typeof rawName === "string" ? rawName : "";

      // Determine dimension name and value from dataset header or category axis
      let dimensionName = "";
      let dimensionValue: string | number = "";

      const dataset = cleanOption.dataset as { source?: unknown[][] } | undefined;
      if (dataset?.source && Array.isArray(dataset.source[0])) {
        const header = dataset.source[0] as string[];
        dimensionName = header[0] ?? "";
        const row = dataset.source[(params.dataIndex ?? 0) + 1] as (string | number)[] | undefined;
        dimensionValue = row?.[0] ?? params.name ?? "";
      } else {
        dimensionName = params.name ?? "";
        dimensionValue = params.name ?? "";
      }

      emitDrillDown({
        chartTitle: title as string,
        seriesName,
        dimensionName,
        dimensionValue,
        dataIndex: params.dataIndex ?? 0,
      });
    });

    const handleResize = () => instance.resize();
    window.addEventListener("resize", handleResize);

    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(containerRef.current);

    return () => {
      window.removeEventListener("resize", handleResize);
      observer.disconnect();
      instance.dispose();
    };
  }, [option, theme, title]);

  useEffect(() => {
    if (aiEditOpen) {
      setTimeout(() => promptInputRef.current?.focus(), 50);
    }
  }, [aiEditOpen]);

  const handleAiEdit = async () => {
    if (!aiPrompt.trim() || aiLoading) return;
    setAiLoading(true);

    try {
      const client = getAPIClient();

      // Create a temporary thread for this single-chart edit
      const thread = await client.threads.create();

      // Use runs.wait to get the final state synchronously
      const result = await client.runs.wait(thread.thread_id, "lead_agent", {
        input: {
          messages: [
            {
              role: "user",
              content: `[CHART EDIT REQUEST — Single chart only, no dashboard regeneration]
You are editing a SINGLE ECharts chart. Return ONLY valid JSON for the ECharts option object. No markdown, no explanation, no code fences.

Current chart title: ${title}
Current chart option: ${JSON.stringify(option)}

User request: ${aiPrompt}

Return ONLY the updated ECharts option JSON object.`,
            },
          ],
        },
        config: { configurable: { thread_id: thread.thread_id } },
      });

      // Extract the last AI message from the result
      const messages = (result as Record<string, unknown>)?.messages;
      if (Array.isArray(messages)) {
        // Find the last AI message
        for (let i = messages.length - 1; i >= 0; i--) {
          const msg = messages[i] as Record<string, unknown>;
          if (msg?.type === "ai" || msg?.role === "assistant") {
            const content = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content);
            if (content) {
              // Try to extract JSON from the response
              const jsonMatch = /\{[\s\S]*\}/.exec(content);
              if (jsonMatch) {
                const newOption = JSON.parse(jsonMatch[0]) as Record<string, unknown>;
                updateAttributes({ option: newOption });
                break;
              }
            }
          }
        }
      }
    } catch (err) {
      console.error("AI Edit failed:", err);
    } finally {
      setAiLoading(false);
      setAiPrompt("");
      setAiEditOpen(false);
    }
  };

  return (
    <NodeViewWrapper>
      <div
        className={cn(
          "group relative my-4 overflow-hidden rounded-xl border transition-all duration-200",
          selected
            ? "border-primary/40 shadow-[0_0_0_3px_rgba(37,99,235,0.1),0_8px_24px_-8px_rgba(0,0,0,0.08)]"
            : hovered
              ? "border-border/80 shadow-[0_4px_16px_-4px_rgba(0,0,0,0.06)]"
              : "border-border/50 shadow-[0_1px_3px_0px_rgba(0,0,0,0.03)]",
        )}
        style={{ background: "linear-gradient(180deg, #ffffff 0%, #fafafa 100%)" }}
        contentEditable={false}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Drag handle */}
        {editor.isEditable && (
          <div
            data-drag-handle
            draggable="true"
            className={cn(
              "absolute -left-8 top-1/2 z-10 -translate-y-1/2 cursor-grab rounded-md p-1 text-muted-foreground transition-opacity hover:bg-muted hover:text-foreground active:cursor-grabbing",
              hovered || selected ? "opacity-100" : "opacity-0",
            )}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="9" cy="5" r="1.5" />
              <circle cx="15" cy="5" r="1.5" />
              <circle cx="9" cy="12" r="1.5" />
              <circle cx="15" cy="12" r="1.5" />
              <circle cx="9" cy="19" r="1.5" />
              <circle cx="15" cy="19" r="1.5" />
            </svg>
          </div>
        )}

        {/* Chart header with action buttons */}
        <div className="flex items-center justify-between px-5 pt-4 pb-0">
          <div className="flex items-center gap-2">
            <p className="text-[13px] font-semibold tracking-[-0.01em] text-foreground/90">
              {title}
            </p>
            {annotationCount > 0 && (
              <span className="flex items-center gap-1 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
                <AlertTriangleIcon className="size-3" />
                {annotationCount}
              </span>
            )}
          </div>
          {editor.isEditable && (hovered || selected || aiEditOpen) && (
            <div className="flex items-center gap-1">
              <button
                onClick={() => { setAiEditOpen(!aiEditOpen); }}
                className={cn(
                  "flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors",
                  aiEditOpen
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:bg-accent",
                )}
              >
                <SparklesIcon className="size-3" />
                AI Edit
              </button>
              <button
                className="flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted"
              >
                <EditIcon className="size-3" />
                Edit
              </button>
            </div>
          )}
        </div>

        {/* AI Edit prompt bar */}
        {aiEditOpen && (
          <div className="mx-4 mt-2 flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2">
            <SparklesIcon className="size-3.5 shrink-0 text-muted-foreground" />
            <input
              ref={promptInputRef}
              type="text"
              placeholder="e.g. Make this a pie chart, change colors to blue..."
              className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground/50"
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleAiEdit();
                if (e.key === "Escape") { setAiEditOpen(false); setAiPrompt(""); }
              }}
            />
            <button
              onClick={() => void handleAiEdit()}
              disabled={aiLoading || !aiPrompt.trim()}
              className={cn(
                "rounded-md px-3 py-1 text-[11px] font-semibold transition-colors",
                aiLoading || !aiPrompt.trim()
                  ? "bg-muted text-muted-foreground cursor-not-allowed"
                  : "bg-foreground text-background hover:bg-foreground/90",
              )}
            >
              {aiLoading ? "..." : "Apply"}
            </button>
            <button
              onClick={() => { setAiEditOpen(false); setAiPrompt(""); }}
              className="text-muted-foreground hover:text-foreground"
            >
              <XIcon className="size-3.5" />
            </button>
          </div>
        )}

        {/* Chart container */}
        <div ref={containerRef} className="h-[280px] w-full px-3 pb-3 pt-1" />
      </div>
    </NodeViewWrapper>
  );
}
