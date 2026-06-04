export const A2UI_DEBUG_DEFAULT_PROPS: Record<string, string> = {
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
    {
      title: "示例卡片",
      value: "1,234",
      subtitle: "较昨日 +12%",
      trend: { direction: "up", value: "+12%" },
    },
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
        {
          title: "开始",
          description: "任务已创建",
          timestamp: "09:00",
          status: "completed",
        },
        {
          title: "进行中",
          description: "当前正在处理",
          timestamp: "12:00",
          status: "active",
        },
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
    {
      src: "https://placehold.co/640x360/png?text=A2UI+Image",
      alt: "示例图片",
      caption: "示例图片",
    },
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
        { level: "high", message: "CPU 使用率过高" },
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
  status: JSON.stringify(
    { status: "running", tag: "系统", label: "运行中" },
    null,
    2,
  ),
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
      alarms: [
        { level: "warning", message: "振动接近预警阈值", timestamp: "14:12" },
      ],
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
  "sub-device-selector": JSON.stringify(
    {
      title: "选择子部件",
      queryParams: { userId: "1", orgId: 0, treeType: 1 },
    },
    null,
    2,
  ),
  "point-selector": JSON.stringify(
    {
      title: "选择测点",
      queryParams: { userId: "1", orgId: 0, treeType: 1 },
    },
    null,
    2,
  ),
  "point-selector-multi": JSON.stringify(
    {
      title: "选择测点（可多选）",
      maxSelect: 10,
      queryParams: { userId: "1", orgId: 0, treeType: 1 },
    },
    null,
    2,
  ),
};
