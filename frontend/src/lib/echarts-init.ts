import { BarChart, FunnelChart, GaugeChart, HeatmapChart, LineChart, PieChart, RadarChart, SankeyChart, ScatterChart, TreemapChart } from "echarts/charts";
import { MarkAreaComponent, MarkLineComponent, MarkPointComponent, DataZoomComponent, GridComponent, LegendComponent, TitleComponent, ToolboxComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, RadarChart,
  GaugeChart, FunnelChart, HeatmapChart, SankeyChart, TreemapChart,
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
  ToolboxComponent, DataZoomComponent, VisualMapComponent,
  MarkLineComponent, MarkPointComponent, MarkAreaComponent,
  CanvasRenderer,
]);

// Register industrial theme for equipment monitoring
echarts.registerTheme("industrial", {
  color: [
    "#10b981", // 正常 - 绿色
    "#f59e0b", // 预警 - 黄色
    "#ef4444", // 报警 - 红色
    "#3b82f6", // 信息 - 蓝色
    "#8b5cf6", // 辅助 - 紫色
    "#06b6d4", // 数据 - 青色
    "#ec4899", // 标记 - 粉色
    "#84cc16", // 补充 - 黄绿
    "#f97316", // 警告 - 橙色
    "#6366f1", // 中性 - 靛蓝
  ],
  backgroundColor: "transparent",
  textStyle: {
    fontFamily: "system-ui, -apple-system, sans-serif",
  },
  title: {
    textStyle: {
      fontWeight: 600,
      fontSize: 16,
    },
  },
  legend: {
    textStyle: {
      fontSize: 12,
    },
  },
  tooltip: {
    backgroundColor: "rgba(255, 255, 255, 0.95)",
    borderColor: "#e5e7eb",
    textStyle: {
      color: "#1f2937",
    },
  },
});

export { echarts };
