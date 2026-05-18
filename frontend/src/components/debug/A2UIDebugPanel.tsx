"use client";

import { useCallback, useMemo, useState } from "react";

import { KNOWN_COMPONENTS } from "@/core/genui";

import { ComponentList } from "./ComponentList";
import { JsonEditor } from "./JsonEditor";
import { PreviewArea } from "./PreviewArea";

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
    { title: "示例卡片", value: "1,234", subtitle: "较昨日 +12%", trend: "up" },
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
        { time: "09:00", content: "开始" },
        { time: "12:00", content: "进行中" },
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
  image: JSON.stringify({}, null, 2),
  gauge: JSON.stringify(
    { value: 65, min: 0, max: 100, unit: "%", label: "示例仪表盘" },
    null,
    2,
  ),
  alarm: JSON.stringify(
    {
      title: "告警列表",
      items: [
        { level: "error", message: "CPU 使用率过高" },
        { level: "warning", message: "磁盘空间不足" },
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
  status: JSON.stringify({ status: "normal", tag: "系统", label: "运行中" }, null, 2),
};

export function A2UIDebugPanel() {
  const [selectedComponent, setSelectedComponent] = useState<string>("");
  const [jsonText, setJsonText] = useState<string>("");

  const handleSelectComponent = useCallback((component: string) => {
    setSelectedComponent(component);
    setJsonText(DEFAULT_PROPS[component] ?? "{}");
  }, []);

  const { parsedProps, parseError } = useMemo(() => {
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
  }, [jsonText]);

  return (
    <div className="flex h-full gap-0">
      <div className="w-64 shrink-0 border-r">
        <ComponentList
          components={KNOWN_COMPONENTS}
          selected={selectedComponent}
          onSelect={handleSelectComponent}
        />
      </div>
      <div className="flex flex-1 flex-col min-h-0">
        <div className="h-1/2 border-b">
          <JsonEditor value={jsonText} onChange={setJsonText} error={parseError} />
        </div>
        <div className="h-1/2">
          <PreviewArea
            componentName={selectedComponent}
            props={parsedProps}
          />
        </div>
      </div>
    </div>
  );
}
