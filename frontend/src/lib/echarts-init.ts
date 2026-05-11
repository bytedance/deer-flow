import { BarChart, FunnelChart, GaugeChart, HeatmapChart, LineChart, PieChart, RadarChart, SankeyChart, ScatterChart, TreemapChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, TitleComponent, ToolboxComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, RadarChart,
  GaugeChart, FunnelChart, HeatmapChart, SankeyChart, TreemapChart,
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
  ToolboxComponent, DataZoomComponent, VisualMapComponent,
  CanvasRenderer,
]);

export { echarts };
