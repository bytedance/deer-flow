"use client";

import { useCallback, useMemo, useState } from "react";

import { KNOWN_COMPONENTS } from "@/core/genui";
import { GenUIRenderer } from "@/components/genui/GenUIRenderer";
import { type UIBlock } from "@/core/genui/store";

import { ComponentList } from "./ComponentList";
import { JsonEditor } from "./JsonEditor";
import { PreviewArea } from "./PreviewArea";

type Mode = "single" | "batch";

const CHART_TYPE_TO_COMPONENT: Record<string, string> = {
  card: "card",
  trend: "echart",
  waveform: "echart",
  spectrum: "echart",
  table: "table",
};

const DEFAULT_CHARTS_JSON = `{
  "total_charts": 3,
  "charts": [
    {
      "chart_type": "card",
      "props": {
        "title": "示例卡片",
        "status": "normal",
        "content": "状态正常 — 未检测到异常",
        "extra": [
          {"label": "类别", "value": "振动"},
          {"label": "异常数", "value": 0}
        ]
      }
    },
    {
      "chart_type": "trend",
      "props": {
        "title": "振动趋势",
        "option": {
          "xAxis": { "type": "category", "data": ["周一", "周二", "周三", "周四", "周五"] },
          "yAxis": { "type": "value", "name": "mm/s" },
          "series": [{ "type": "line", "data": [2.1, 2.3, 2.2, 2.5, 2.4] }]
        }
      }
    },
    {
      "chart_type": "table",
      "props": {
        "title": "特征汇总",
        "columns": [
          {"title": "测点", "dataIndex": "name"},
          {"title": "状态", "dataIndex": "status"}
        ],
        "dataSource": [
          {"name": "测点A", "status": "正常"},
          {"name": "测点B", "status": "警告"}
        ]
      }
    }
  ]
}`;

const DEFAULT_PROPS: Record<string, string> = {
  chart: JSON.stringify(
    {
      chart_type: "bar",
      title: "示例图表",
      x_key: "name",
      y_key: "value",
      data: [
        { name: "A", value: 30 },
        { name: "B", value: 50 },
        { name: "C", value: 40 },
      ],
    },
    null,
    2,
  ),
  echart: JSON.stringify(
    {
      height: 400,
      option: {
        xAxis: { type: "category", data: ["Mon", "Tue", "Wed", "Thu", "Fri"] },
        yAxis: { type: "value" },
        series: [{ type: "line", data: [120, 200, 150, 80, 70] }],
      },
    },
    null,
    2,
  ),
  table: JSON.stringify(
    {
      title: "示例表格",
      columns: [
        { key: "name", label: "名称" },
        { key: "value", label: "数值" },
      ],
      data: [
        { name: "项目A", value: 100 },
        { name: "项目B", value: 200 },
      ],
    },
    null,
    2,
  ),
  card: JSON.stringify(
    { title: "示例卡片", value: "1,234", subtitle: "较昨日 +12%", trend: { direction: "up", value: "+12%" } },
    null,
    2,
  ),
  form: JSON.stringify(
    {
      title: "示例表单",
      fields: [
        { name: "username", type: "text", label: "用户名" },
        { name: "email", type: "email", label: "邮箱" },
      ],
      submit_label: "提交",
    },
    null,
    2,
  ),
  confirm: JSON.stringify(
    { title: "确认操作", message: "确定要执行此操作吗？" },
    null,
    2,
  ),
  code: JSON.stringify(
    { code: 'console.log("Hello, A2UI!")', language: "javascript", title: "示例代码" },
    null,
    2,
  ),
  timeline: JSON.stringify(
    {
      title: "时间线",
      events: [
        { title: "开始", description: "任务已创建", timestamp: "09:00", status: "completed" },
        { title: "进行中", description: "当前正在处理", timestamp: "12:00", status: "active" },
      ],
    },
    null,
    2,
  ),
  layout: JSON.stringify({ layout_type: "grid", columns: 2, gap: 4 }, null, 2),
  markdown: JSON.stringify(
    { content: "# 标题\n\n这是 **Markdown** 内容。\n\n- 项目 1\n- 项目 2" },
    null,
    2,
  ),
  image: JSON.stringify(
    { src: "https://placehold.co/640x360/png?text=A2UI+Image", alt: "示例图片", caption: "示例图片" },
    null,
    2,
  ),
  gauge: JSON.stringify(
    { value: 65, min: 0, max: 100, unit: "%", label: "示例仪表盘" },
    null,
    2,
  ),
  alarm: JSON.stringify(
    {
      title: "告警列表",
      items: [
        { level: "critical", message: "CPU 使用率过高" },
        { level: "medium", message: "磁盘空间不足" },
      ],
    },
    null,
    2,
  ),
  metric: JSON.stringify(
    { tag: "温度", label: "当前温度", value: 25.5, unit: "°C" },
    null,
    2,
  ),
  status: JSON.stringify({ status: "running", tag: "系统", label: "运行中" }, null, 2),
  "industrial-dashboard": JSON.stringify(
    {
      deviceName: "压缩机 K-301",
      lastUpdated: "2026-05-28 14:30",
      healthScore: 82,
      healthScoreThresholds: { warn: 70, error: 50, critical: 30 },
      metrics: [
        { label: "振动", value: 4.8, unit: "mm/s", status: "warning" },
        { label: "轴承温度", value: 78.6, unit: "°C", status: "normal" },
        { label: "出口压力", value: 1.25, unit: "MPa", status: "normal" },
      ],
      alarms: [{ level: "warning", message: "振动接近预警阈值", timestamp: "14:12" }],
      trend: [
        { time: "10:00", value: 88 },
        { time: "12:00", value: 85 },
        { time: "14:00", value: 82 },
      ],
    },
    null,
    2,
  ),
  "device-selector": JSON.stringify(
    {
      title: "选择设备",
      queryParams: { userId: "1", orgId: 0, treeType: 1 },
      filterDeviceType: 4,
    },
    null,
    2,
  ),
  "device-selector-multi": JSON.stringify(
    {
      title: "选择设备（可多选）",
      maxSelect: 5,
      queryParams: { userId: "1", orgId: 0, treeType: 1 },
      filterDeviceType: 1,
    },
    null,
    2,
  ),
};

export function A2UIDebugPanel() {
  const [mode, setMode] = useState<Mode>("single");
  const [selectedComponent, setSelectedComponent] = useState<string>("");
  const [jsonText, setJsonText] = useState<string>("");

  const handleSelectComponent = useCallback((component: string) => {
    setMode("single");
    setSelectedComponent(component);
    setJsonText(DEFAULT_PROPS[component] ?? "{}");
  }, []);

  const { parsedProps, parseError } = useMemo(() => {
    if (mode === "batch") {
      return { parsedProps: null, parseError: null };
    }
    if (!jsonText.trim()) {
      return { parsedProps: null, parseError: null };
    }
    try {
      const parsed = JSON.parse(jsonText);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return { parsedProps: null, parseError: "JSON 必须是一个对象" };
      }
      return { parsedProps: parsed as Record<string, unknown>, parseError: null };
    } catch (e) {
      const message = e instanceof SyntaxError ? e.message : "无法解析 JSON";
      return { parsedProps: null, parseError: message };
    }
  }, [jsonText, mode]);

  // 批量模式：解析 charts.json
  const { batchBlocks, batchError } = useMemo(() => {
    if (mode !== "batch" || !jsonText.trim()) {
      return { batchBlocks: [] as UIBlock[], batchError: null as string | null };
    }
    try {
      const parsed = JSON.parse(jsonText);
      const charts = parsed.charts;
      if (!Array.isArray(charts)) {
        return { batchBlocks: [], batchError: "charts.json 缺少 charts 数组" };
      }
      const blocks: UIBlock[] = charts.map((chart: { chart_type?: string; props?: Record<string, unknown> }, i: number) => {
        const component = CHART_TYPE_TO_COMPONENT[chart.chart_type || ""] || chart.chart_type || "markdown";
        return {
          schema_version: "1.0",
          type: "ui_block" as const,
          action: "create" as const,
          block_id: `batch-${i}`,
          component,
          props: chart.props || {},
          interactive: false,
        };
      });
      return { batchBlocks: blocks, batchError: null };
    } catch (e) {
      return { batchBlocks: [], batchError: e instanceof SyntaxError ? e.message : "JSON 解析失败" };
    }
  }, [jsonText, mode]);

  const handleModeChange = useCallback((newMode: Mode) => {
    setMode(newMode);
    if (newMode === "batch") {
      setSelectedComponent("");
      setJsonText(DEFAULT_CHARTS_JSON);
    }
  }, []);

  return (
    <div className="flex h-full gap-0">
      {/* 左侧边栏 */}
      <div className="w-64 shrink-0 border-r flex flex-col">
        {/* 模式切换 */}
        <div className="border-b p-2 flex gap-1">
          <button
            className={`flex-1 rounded px-2 py-1 text-xs font-medium ${
              mode === "single" ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/80"
            }`}
            onClick={() => handleModeChange("single")}
          >
            单个组件
          </button>
          <button
            className={`flex-1 rounded px-2 py-1 text-xs font-medium ${
              mode === "batch" ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/80"
            }`}
            onClick={() => handleModeChange("batch")}
          >
            批量渲染
          </button>
        </div>
        {/* 组件列表（仅单个模式） */}
        {mode === "single" && (
          <ComponentList
            components={KNOWN_COMPONENTS}
            selected={selectedComponent}
            onSelect={handleSelectComponent}
          />
        )}
        {/* 批量模式提示 */}
        {mode === "batch" && (
          <div className="p-3 text-xs text-muted-foreground">
            <p className="mb-2">粘贴 charts.json 内容：</p>
            <code className="text-[10px]">generate_charts.py</code>
            <p className="mt-2">输出格式：</p>
            <pre className="mt-1 rounded bg-muted p-2 text-[10px] overflow-x-auto">
{`{
  "charts": [
    {
      "chart_type": "card|trend|...",
      "props": {...}
    }
  ]
}`}
            </pre>
          </div>
        )}
      </div>
      {/* 右侧编辑+预览 */}
      <div className="flex flex-1 flex-col min-h-0">
        <div className="h-1/2 border-b">
          <JsonEditor value={jsonText} onChange={setJsonText} error={parseError || batchError} />
        </div>
        <div className="h-1/2">
          {mode === "single" ? (
            <PreviewArea
              componentName={selectedComponent}
              props={parsedProps}
            />
          ) : (
            <BatchPreviewArea blocks={batchBlocks} count={batchBlocks.length} />
          )}
        </div>
      </div>
    </div>
  );
}

/** 批量渲染预览区域 */
function BatchPreviewArea({ blocks, count }: { blocks: UIBlock[]; count: number }) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">批量预览</h3>
        <span className="text-xs text-muted-foreground">{count} 个组件</span>
      </div>
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {blocks.length === 0 && (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            请在左侧编辑器中粘贴 charts.json 内容
          </div>
        )}
        {blocks.map((block) => (
          <div key={block.block_id} className="rounded border bg-background p-2">
            <div className="mb-1 text-xs text-muted-foreground">
              [{block.component}] {typeof block.props.title === "string" ? block.props.title : ""}
            </div>
            <GenUIRenderer block={block} disableExpiration />
          </div>
        ))}
      </div>
    </div>
  );
}
