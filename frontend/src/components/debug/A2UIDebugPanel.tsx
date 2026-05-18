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
  "device-selector": JSON.stringify(
    {
      title: "选择设备",
      treeData: [
        {
          id: "100",
          label: "因思科技",
          type: 14,
          path: "因思科技",
          parentId: "0",
          displayOrder: 1,
          children: [
            {
              id: "200",
              label: "海科瑞林",
              type: 13,
              path: "因思科技/海科瑞林",
              parentId: "100",
              displayOrder: 1,
              children: [
                {
                  id: "300",
                  label: "机泵在线监测系统",
                  type: 12,
                  path: "因思科技/海科瑞林/机泵系统",
                  parentId: "200",
                  displayOrder: 1,
                  children: [
                    {
                      id: "400",
                      label: "运行一部",
                      type: 11,
                      path: "因思科技/海科瑞林/机泵系统/运行一部",
                      parentId: "300",
                      displayOrder: 1,
                      children: [
                        { id: "d1", label: "焦化装置-泵A", type: 4, path: ".../焦化装置-泵A", parentId: "400", displayOrder: 1 },
                        { id: "d2", label: "常减压装置-泵B", type: 4, path: ".../常减压装置-泵B", parentId: "400", displayOrder: 2 },
                        { id: "d3", label: "催化裂化压缩机组", type: 1, path: ".../催化裂化压缩机组", parentId: "400", displayOrder: 3 },
                      ],
                    },
                    {
                      id: "401",
                      label: "运行二部",
                      type: 11,
                      path: "因思科技/海科瑞林/机泵系统/运行二部",
                      parentId: "300",
                      displayOrder: 2,
                      children: [
                        { id: "d4", label: "气分装置-泵C", type: 4, path: ".../气分装置-泵C", parentId: "401", displayOrder: 1 },
                        { id: "d5", label: "TMP装置-泵D", type: 4, path: ".../TMP装置-泵D", parentId: "401", displayOrder: 2 },
                        { id: "d6", label: "加氢反应器R-101", type: 6, path: ".../加氢反应器R-101", parentId: "401", displayOrder: 3 },
                      ],
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    },
    null,
    2,
  ),
  "device-selector-multi": JSON.stringify(
    {
      title: "选择设备（可多选）",
      maxSelect: 5,
      treeData: [
        {
          id: "100",
          label: "因思科技",
          type: 14,
          path: "因思科技",
          parentId: "0",
          displayOrder: 1,
          children: [
            {
              id: "200",
              label: "海科瑞林",
              type: 13,
              path: "因思科技/海科瑞林",
              parentId: "100",
              displayOrder: 1,
              children: [
                {
                  id: "500",
                  label: "大机组在线监测系统",
                  type: 12,
                  path: "因思科技/海科瑞林/大机组系统",
                  parentId: "200",
                  displayOrder: 1,
                  children: [
                    {
                      id: "600",
                      label: "运行四部",
                      type: 11,
                      path: "因思科技/海科瑞林/大机组系统/运行四部",
                      parentId: "500",
                      displayOrder: 1,
                      children: [
                        { id: "m1", label: "15万吨液化气项目机组", type: 1, path: ".../15万吨液化气", parentId: "600", displayOrder: 1 },
                        { id: "m2", label: "润滑油联产芳烃机组", type: 1, path: ".../润滑油联产芳烃", parentId: "600", displayOrder: 2 },
                        { id: "m3", label: "往复压缩机K-201", type: 9, path: ".../往复压缩机K-201", parentId: "600", displayOrder: 3 },
                      ],
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    },
    null,
    2,
  ),
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
