export interface ChartTemplate {
  type: string;
  label: string;
  description: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  option: any;
}

export const CHART_TEMPLATES: ChartTemplate[] = [
  {
    type: "line",
    label: "Line Chart",
    description: "Trends over time",
    option: {
      title: { text: "Line Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] },
      yAxis: { type: "value" },
      series: [{ type: "line", data: [150, 230, 224, 218, 135, 147, 260], smooth: true, color: "#3b82f6" }],
    },
  },
  {
    type: "area",
    label: "Area Chart",
    description: "Filled line chart for volume",
    option: {
      title: { text: "Area Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"] },
      yAxis: { type: "value" },
      series: [{
        type: "line", data: [820, 932, 901, 1034, 1290, 1330],
        areaStyle: { color: "rgba(59,130,246,0.2)" }, smooth: true, color: "#3b82f6",
      }],
    },
  },
  {
    type: "bar",
    label: "Bar Chart",
    description: "Compare categories",
    option: {
      title: { text: "Bar Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Category A", "Category B", "Category C", "Category D", "Category E"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: [120, 200, 150, 80, 170], color: "#3b82f6" }],
    },
  },
  {
    type: "bar-horizontal",
    label: "Horizontal Bar",
    description: "Horizontal comparison",
    option: {
      title: { text: "Horizontal Bar Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "value" },
      yAxis: { type: "category", data: ["Item A", "Item B", "Item C", "Item D", "Item E"] },
      series: [{ type: "bar", data: [120, 200, 150, 80, 170], color: "#3b82f6" }],
    },
  },
  {
    type: "stacked-bar",
    label: "Stacked Bar",
    description: "Stacked category comparison",
    option: {
      title: { text: "Stacked Bar Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { containLabel: true, left: 12, right: 12, bottom: 32, top: 40 },
      xAxis: { type: "category", data: ["Q1", "Q2", "Q3", "Q4"] },
      yAxis: { type: "value" },
      series: [
        { name: "Product A", type: "bar", stack: "total", data: [320, 302, 301, 334], color: "#2563eb" },
        { name: "Product B", type: "bar", stack: "total", data: [120, 132, 101, 134], color: "#60a5fa" },
        { name: "Product C", type: "bar", stack: "total", data: [220, 182, 191, 234], color: "#93c5fd" },
      ],
    },
  },
  {
    type: "pie",
    label: "Pie Chart",
    description: "Proportional distribution",
    option: {
      title: { text: "Pie Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      series: [{
        type: "pie", radius: "60%", center: ["50%", "50%"],
        data: [
          { value: 1048, name: "Category A" },
          { value: 735, name: "Category B" },
          { value: 580, name: "Category C" },
          { value: 484, name: "Category D" },
          { value: 300, name: "Category E" },
        ],
        color: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe"],
        label: { formatter: "{b}\n{d}%" },
      }],
    },
  },
  {
    type: "donut",
    label: "Donut Chart",
    description: "Pie with center hole",
    option: {
      title: { text: "Donut Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      series: [{
        type: "pie", radius: ["40%", "65%"], center: ["50%", "50%"],
        data: [
          { value: 1048, name: "Segment A" },
          { value: 735, name: "Segment B" },
          { value: 580, name: "Segment C" },
          { value: 484, name: "Segment D" },
        ],
        color: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd"],
        label: { formatter: "{b}\n{d}%" },
      }],
    },
  },
  {
    type: "scatter",
    label: "Scatter Plot",
    description: "Correlation between variables",
    option: {
      title: { text: "Scatter Plot", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "value", name: "X Axis" },
      yAxis: { type: "value", name: "Y Axis" },
      series: [{
        type: "scatter",
        data: [[10, 8.04], [8, 6.95], [13, 7.58], [9, 8.81], [11, 8.33],
               [14, 9.96], [6, 7.24], [4, 4.26], [12, 10.84], [7, 4.82], [5, 5.68]],
        color: "#3b82f6",
      }],
    },
  },
  {
    type: "bubble",
    label: "Bubble Chart",
    description: "Scatter with size dimension",
    option: {
      title: { text: "Bubble Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "value", name: "X" },
      yAxis: { type: "value", name: "Y" },
      series: [{
        type: "scatter",
        symbolSize: (data: number[]) => Math.sqrt(data[2] ?? 0) * 4,
        data: [[10, 8, 100], [8, 7, 60], [13, 8, 200], [9, 9, 80], [11, 8, 150],
               [14, 10, 120], [6, 7, 40], [4, 4, 30], [12, 11, 180], [7, 5, 50]],
        color: "#3b82f6",
      }],
    },
  },
  {
    type: "radar",
    label: "Radar Chart",
    description: "Multi-dimensional comparison",
    option: {
      title: { text: "Radar Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: {},
      legend: { bottom: 0 },
      radar: {
        indicator: [
          { name: "Sales", max: 100 },
          { name: "Admin", max: 100 },
          { name: "Tech", max: 100 },
          { name: "Support", max: 100 },
          { name: "Marketing", max: 100 },
          { name: "Development", max: 100 },
        ],
      },
      series: [{
        type: "radar",
        data: [
          { value: [80, 60, 90, 70, 65, 85], name: "Team A" },
          { value: [60, 80, 70, 85, 75, 65], name: "Team B" },
        ],
        color: ["#2563eb", "#60a5fa"],
      }],
    },
  },
  {
    type: "heatmap",
    label: "Heatmap",
    description: "Matrix intensity visualization",
    option: {
      title: { text: "Heatmap", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { position: "top" },
      grid: { containLabel: true, left: 12, right: 40, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Mon", "Tue", "Wed", "Thu", "Fri"] },
      yAxis: { type: "category", data: ["Morning", "Afternoon", "Evening"] },
      visualMap: { min: 0, max: 100, calculable: true, orient: "vertical", right: 0, top: "center", inRange: { color: ["#dbeafe", "#60a5fa", "#2563eb"] } },
      series: [{
        type: "heatmap",
        data: [
          [0, 0, 52], [1, 0, 73], [2, 0, 85], [3, 0, 45], [4, 0, 68],
          [0, 1, 91], [1, 1, 62], [2, 1, 78], [3, 1, 88], [4, 1, 55],
          [0, 2, 38], [1, 2, 45], [2, 2, 33], [3, 2, 92], [4, 2, 71],
        ],
        label: { show: true },
      }],
    },
  },
  {
    type: "treemap",
    label: "Treemap",
    description: "Hierarchical proportional areas",
    option: {
      title: { text: "Treemap", left: "center", textStyle: { fontSize: 14 } },
      tooltip: {},
      series: [{
        type: "treemap",
        data: [
          { name: "Category A", value: 560, children: [
            { name: "A1", value: 320 }, { name: "A2", value: 240 },
          ]},
          { name: "Category B", value: 420, children: [
            { name: "B1", value: 200 }, { name: "B2", value: 120 }, { name: "B3", value: 100 },
          ]},
          { name: "Category C", value: 320 },
          { name: "Category D", value: 180 },
        ],
        color: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd"],
        label: { formatter: "{b}\n{c}" },
      }],
    },
  },
  {
    type: "sunburst",
    label: "Sunburst",
    description: "Hierarchical radial chart",
    option: {
      title: { text: "Sunburst", left: "center", textStyle: { fontSize: 14 } },
      series: [{
        type: "sunburst",
        data: [
          { name: "A", value: 10, children: [
            { name: "A1", value: 4 }, { name: "A2", value: 6 },
          ]},
          { name: "B", value: 15, children: [
            { name: "B1", value: 7 }, { name: "B2", value: 5 }, { name: "B3", value: 3 },
          ]},
          { name: "C", value: 8 },
        ],
        radius: ["15%", "75%"],
        label: { rotate: "radial" },
        color: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe"],
      }],
    },
  },
  {
    type: "funnel",
    label: "Funnel",
    description: "Stage progression",
    option: {
      title: { text: "Funnel Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      series: [{
        type: "funnel", left: "10%", width: "80%", top: 40, bottom: 20,
        min: 0, max: 100, sort: "descending", gap: 2,
        label: { show: true, position: "inside", formatter: "{b}: {c}%" },
        data: [
          { value: 100, name: "Visitors" },
          { value: 80, name: "Leads" },
          { value: 60, name: "Qualified" },
          { value: 40, name: "Proposals" },
          { value: 20, name: "Closed" },
        ],
        color: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe"],
      }],
    },
  },
  {
    type: "gauge",
    label: "Gauge",
    description: "KPI meter / speedometer",
    option: {
      series: [{
        type: "gauge",
        progress: { show: true, width: 18 },
        axisLine: { lineStyle: { width: 18 } },
        axisTick: { show: false },
        splitLine: { length: 12, lineStyle: { width: 2, color: "#999" } },
        axisLabel: { distance: 25, fontSize: 11 },
        anchor: { show: true, showAbove: true, size: 20, itemStyle: { borderWidth: 8, borderColor: "#2563eb" } },
        title: { show: true, offsetCenter: [0, "70%"], fontSize: 14 },
        detail: { valueAnimation: true, fontSize: 28, offsetCenter: [0, "45%"], formatter: "{value}%", color: "#2563eb" },
        data: [{ value: 72, name: "Progress" }],
        color: "#2563eb",
      }],
    },
  },
  {
    type: "candlestick",
    label: "Candlestick",
    description: "OHLC financial chart",
    option: {
      title: { text: "Candlestick Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7"] },
      yAxis: { type: "value" },
      series: [{
        type: "candlestick",
        data: [
          [20, 34, 10, 38], [40, 35, 30, 50], [31, 38, 33, 44],
          [38, 15, 5, 42], [20, 32, 18, 36], [30, 45, 28, 48], [42, 38, 35, 50],
        ],
        itemStyle: { color: "#2563eb", color0: "#60a5fa", borderColor: "#2563eb", borderColor0: "#60a5fa" },
      }],
    },
  },
  {
    type: "boxplot",
    label: "Box Plot",
    description: "Statistical distribution",
    option: {
      title: { text: "Box Plot", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Group A", "Group B", "Group C"] },
      yAxis: { type: "value" },
      series: [{
        type: "boxplot",
        data: [
          [655, 850, 940, 980, 1175],
          [672, 780, 840, 930, 1070],
          [780, 840, 920, 1010, 1150],
        ],
        itemStyle: { color: "#dbeafe", borderColor: "#2563eb" },
      }],
    },
  },
  {
    type: "sankey",
    label: "Sankey",
    description: "Flow between nodes",
    option: {
      title: { text: "Sankey Diagram", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      series: [{
        type: "sankey",
        layout: "none",
        emphasis: { focus: "adjacency" },
        data: [
          { name: "Source A" }, { name: "Source B" }, { name: "Source C" },
          { name: "Process X" }, { name: "Process Y" },
          { name: "Output 1" }, { name: "Output 2" },
        ],
        links: [
          { source: "Source A", target: "Process X", value: 5 },
          { source: "Source A", target: "Process Y", value: 3 },
          { source: "Source B", target: "Process X", value: 4 },
          { source: "Source C", target: "Process Y", value: 6 },
          { source: "Process X", target: "Output 1", value: 7 },
          { source: "Process X", target: "Output 2", value: 2 },
          { source: "Process Y", target: "Output 1", value: 4 },
          { source: "Process Y", target: "Output 2", value: 5 },
        ],
        color: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#1d4ed8", "#1e40af"],
      }],
    },
  },
  {
    type: "graph",
    label: "Graph / Network",
    description: "Node-link network diagram",
    option: {
      title: { text: "Network Graph", left: "center", textStyle: { fontSize: 14 } },
      tooltip: {},
      series: [{
        type: "graph",
        layout: "force",
        roam: true,
        force: { repulsion: 200, edgeLength: 100 },
        label: { show: true, position: "right" },
        data: [
          { name: "Node 1", symbolSize: 40 }, { name: "Node 2", symbolSize: 30 },
          { name: "Node 3", symbolSize: 35 }, { name: "Node 4", symbolSize: 25 },
          { name: "Node 5", symbolSize: 20 }, { name: "Node 6", symbolSize: 28 },
        ],
        links: [
          { source: "Node 1", target: "Node 2" }, { source: "Node 1", target: "Node 3" },
          { source: "Node 2", target: "Node 4" }, { source: "Node 3", target: "Node 5" },
          { source: "Node 3", target: "Node 6" }, { source: "Node 4", target: "Node 6" },
        ],
        lineStyle: { opacity: 0.6, width: 2 },
        color: ["#2563eb"],
        itemStyle: { color: "#2563eb" },
      }],
    },
  },
  {
    type: "parallel",
    label: "Parallel Coordinates",
    description: "Multi-axis comparison",
    option: {
      title: { text: "Parallel Coordinates", left: "center", textStyle: { fontSize: 14 } },
      parallelAxis: [
        { dim: 0, name: "Metric A" },
        { dim: 1, name: "Metric B" },
        { dim: 2, name: "Metric C" },
        { dim: 3, name: "Metric D" },
        { dim: 4, name: "Metric E" },
      ],
      series: [{
        type: "parallel",
        lineStyle: { width: 2, opacity: 0.5 },
        data: [
          [1, 55, 9, 56, 0.46],
          [2, 25, 11, 21, 0.65],
          [3, 56, 7, 63, 0.3],
          [4, 33, 7, 29, 0.33],
          [5, 42, 24, 44, 0.76],
          [6, 82, 58, 90, 1.77],
        ],
        color: "#2563eb",
      }],
    },
  },
  {
    type: "themeRiver",
    label: "Theme River",
    description: "Stacked stream graph",
    option: {
      title: { text: "Theme River", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      singleAxis: { type: "time", bottom: 30 },
      series: [{
        type: "themeRiver",
        data: [
          ["2020/01", 10, "Product A"], ["2020/02", 15, "Product A"], ["2020/03", 25, "Product A"],
          ["2020/04", 30, "Product A"], ["2020/05", 22, "Product A"], ["2020/06", 18, "Product A"],
          ["2020/01", 20, "Product B"], ["2020/02", 18, "Product B"], ["2020/03", 22, "Product B"],
          ["2020/04", 28, "Product B"], ["2020/05", 35, "Product B"], ["2020/06", 30, "Product B"],
          ["2020/01", 5, "Product C"], ["2020/02", 10, "Product C"], ["2020/03", 15, "Product C"],
          ["2020/04", 12, "Product C"], ["2020/05", 18, "Product C"], ["2020/06", 22, "Product C"],
        ],
        color: ["#2563eb", "#60a5fa", "#93c5fd"],
      }],
    },
  },
  // ──────────────────────────────────────────────────────────────
  // New chart templates below
  // ──────────────────────────────────────────────────────────────
  {
    type: "waterfall",
    label: "Waterfall Chart",
    description: "Cascade showing cumulative effect",
    option: {
      title: { text: "Waterfall Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: {
        trigger: "axis",
        formatter: (params: { seriesName: string; value: number; name: string }[]) => {
          const val = params.find((p) => p.seriesName !== "Base");
          return val ? `${val.name}: ${val.value}` : "";
        },
      },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Start", "Jan", "Feb", "Mar", "Apr", "May", "Total"] },
      yAxis: { type: "value" },
      series: [
        {
          name: "Base",
          type: "bar",
          stack: "waterfall",
          itemStyle: { borderColor: "transparent", color: "transparent" },
          emphasis: { itemStyle: { borderColor: "transparent", color: "transparent" } },
          data: [0, 900, 1100, 900, 1050, 950, 0],
        },
        {
          name: "Increase",
          type: "bar",
          stack: "waterfall",
          data: [900, 200, 0, 150, 0, 0, 0],
          itemStyle: { color: "#2563eb" },
          label: { show: true, position: "top" },
        },
        {
          name: "Decrease",
          type: "bar",
          stack: "waterfall",
          data: [0, 0, -200, 0, -100, -50, 0],
          itemStyle: { color: "#93c5fd" },
          label: { show: true, position: "bottom" },
        },
        {
          name: "Total",
          type: "bar",
          stack: "waterfall",
          data: [0, 0, 0, 0, 0, 0, 900],
          itemStyle: { color: "#1d4ed8" },
          label: { show: true, position: "top" },
        },
      ],
    },
  },
  {
    type: "rose",
    label: "Nightingale Rose",
    description: "Pie chart with radius encoding value",
    option: {
      title: { text: "Nightingale Rose Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      series: [{
        type: "pie",
        radius: ["20%", "70%"],
        center: ["50%", "50%"],
        roseType: "radius",
        itemStyle: { borderRadius: 5 },
        data: [
          { value: 40, name: "Category A" },
          { value: 38, name: "Category B" },
          { value: 32, name: "Category C" },
          { value: 30, name: "Category D" },
          { value: 28, name: "Category E" },
          { value: 26, name: "Category F" },
          { value: 22, name: "Category G" },
          { value: 18, name: "Category H" },
        ],
        color: ["#1e3a8a", "#1e40af", "#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe"],
        label: { formatter: "{b}\n{d}%" },
      }],
    },
  },
  {
    type: "polar-bar",
    label: "Polar Bar Chart",
    description: "Bar chart on polar coordinates",
    option: {
      title: { text: "Polar Bar Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      angleAxis: { type: "category", data: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] },
      radiusAxis: {},
      polar: {},
      series: [{
        type: "bar",
        data: [1, 2, 3, 4, 3, 5, 1],
        coordinateSystem: "polar",
        color: "#3b82f6",
      }],
    },
  },
  {
    type: "polar-line",
    label: "Polar Line Chart",
    description: "Line chart on polar coordinates",
    option: {
      title: { text: "Polar Line Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      polar: { radius: ["10%", "70%"] },
      angleAxis: { type: "category", data: ["N", "NE", "E", "SE", "S", "SW", "W", "NW"], boundaryGap: false },
      radiusAxis: { min: 0 },
      series: [{
        type: "line",
        data: [5, 7, 3, 8, 4, 6, 9, 5],
        coordinateSystem: "polar",
        areaStyle: { color: "rgba(59,130,246,0.2)" },
        color: "#3b82f6",
        smooth: true,
      }],
    },
  },
  {
    type: "pictorial-bar",
    label: "Pictorial Bar Chart",
    description: "Bar chart with pictorial symbols",
    option: {
      title: { text: "Pictorial Bar Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["February", "March", "April", "May", "June", "July"] },
      yAxis: { type: "value" },
      series: [{
        type: "pictorialBar",
        symbol: "roundRect",
        symbolRepeat: true,
        symbolSize: [18, 6],
        symbolMargin: 2,
        data: [125, 200, 150, 300, 260, 340],
        color: "#3b82f6",
      }],
    },
  },
  {
    type: "calendar-heatmap",
    label: "Calendar Heatmap",
    description: "Activity heatmap over calendar days",
    option: {
      title: { text: "Calendar Heatmap", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { position: "top", formatter: (p: { value: [string, number] }) => `${p.value[0]}: ${p.value[1]}` },
      visualMap: { min: 0, max: 300, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#dbeafe", "#93c5fd", "#3b82f6", "#1d4ed8"] } },
      calendar: { top: 50, left: 30, right: 30, cellSize: ["auto", 13], range: "2025-01", yearLabel: { show: false }, monthLabel: { show: true }, dayLabel: { firstDay: 1, nameMap: "en" }, itemStyle: { borderWidth: 0.5, borderColor: "#e5e7eb" } },
      series: [{
        type: "heatmap",
        coordinateSystem: "calendar",
        data: (() => {
          const data: [string, number][] = [];
          for (let i = 1; i <= 31; i++) {
            const day = i.toString().padStart(2, "0");
            data.push([`2025-01-${day}`, Math.round(Math.random() * 300)]);
          }
          return data;
        })(),
      }],
    },
  },
  {
    type: "map-bubble",
    label: "Bubble Map (Grid)",
    description: "Scatter simulating geographic bubbles",
    option: {
      title: { text: "Regional Sales Distribution", left: "center", textStyle: { fontSize: 14 } },
      tooltip: {
        trigger: "item",
        formatter: (params: { data: number[]; marker: string }) => `${params.marker} Region (${params.data[0]}, ${params.data[1]})<br/>Sales: ${params.data[2]}`,
      },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "value", name: "Longitude", min: 0, max: 100, axisLabel: { show: false }, splitLine: { show: false } },
      yAxis: { type: "value", name: "Latitude", min: 0, max: 100, axisLabel: { show: false }, splitLine: { show: false } },
      series: [{
        type: "scatter",
        symbolSize: (data: number[]) => Math.sqrt(data[2] ?? 0) * 2.5,
        data: [
          [20, 70, 450], [35, 80, 280], [50, 65, 620],
          [65, 45, 380], [80, 75, 520], [30, 40, 190],
          [55, 30, 310], [75, 55, 410], [45, 85, 250],
          [15, 50, 170],
        ],
        itemStyle: { color: "#3b82f6", opacity: 0.7 },
        label: { show: false },
      }],
    },
  },
  {
    type: "step-line",
    label: "Step Line Chart",
    description: "Line chart with step interpolation",
    option: {
      title: { text: "Step Line Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] },
      yAxis: { type: "value" },
      series: [{
        type: "line",
        step: "middle",
        data: [120, 132, 101, 180, 190, 150, 230],
        color: "#3b82f6",
        lineStyle: { width: 2 },
        areaStyle: { color: "rgba(59,130,246,0.1)" },
      }],
    },
  },
  {
    type: "stacked-area",
    label: "Stacked Area Chart",
    description: "Layered area showing composition over time",
    option: {
      title: { text: "Stacked Area Chart", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { containLabel: true, left: 12, right: 12, bottom: 32, top: 40 },
      xAxis: { type: "category", data: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"] },
      yAxis: { type: "value" },
      series: [
        { name: "Email", type: "line", stack: "total", areaStyle: { opacity: 0.6 }, data: [120, 132, 101, 134, 90, 230, 210], color: "#1d4ed8" },
        { name: "Social", type: "line", stack: "total", areaStyle: { opacity: 0.6 }, data: [220, 182, 191, 234, 290, 330, 310], color: "#3b82f6" },
        { name: "Direct", type: "line", stack: "total", areaStyle: { opacity: 0.6 }, data: [150, 232, 201, 154, 190, 330, 410], color: "#60a5fa" },
        { name: "Referral", type: "line", stack: "total", areaStyle: { opacity: 0.6 }, data: [320, 332, 301, 334, 390, 330, 320], color: "#93c5fd" },
      ],
    },
  },
  {
    type: "mixed-line-bar",
    label: "Mixed Line & Bar",
    description: "Combined bar and line on same axis",
    option: {
      title: { text: "Revenue & Growth Rate", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { containLabel: true, left: 12, right: 12, bottom: 32, top: 40 },
      xAxis: { type: "category", data: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"] },
      yAxis: [
        { type: "value", name: "Revenue ($K)" },
        { type: "value", name: "Growth (%)", alignTicks: true },
      ],
      series: [
        { name: "Revenue", type: "bar", data: [260, 310, 280, 350, 420, 480], color: "#3b82f6" },
        { name: "Growth Rate", type: "line", yAxisIndex: 1, data: [6.5, 8.2, 5.1, 9.3, 12.0, 14.5], smooth: true, color: "#1d4ed8", lineStyle: { width: 2 } },
      ],
    },
  },
  {
    type: "multi-axis",
    label: "Dual Y-Axis",
    description: "Two different scales on left and right",
    option: {
      title: { text: "Temperature & Precipitation", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { containLabel: true, left: 12, right: 12, bottom: 32, top: 40 },
      xAxis: { type: "category", data: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] },
      yAxis: [
        { type: "value", name: "Temp (°C)", position: "left" },
        { type: "value", name: "Rain (mm)", position: "right", alignTicks: true },
      ],
      series: [
        { name: "Temperature", type: "line", data: [2, 4, 8, 14, 18, 22, 25, 24, 20, 14, 8, 3], smooth: true, color: "#2563eb", lineStyle: { width: 2 } },
        { name: "Precipitation", type: "bar", yAxisIndex: 1, data: [50, 42, 55, 60, 72, 85, 90, 82, 68, 62, 55, 48], color: "#93c5fd" },
      ],
    },
  },
  {
    type: "progress-bar",
    label: "Progress Bars",
    description: "Horizontal bars styled as progress indicators",
    option: {
      title: { text: "Project Completion", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis", formatter: "{b}: {c}%" },
      grid: { containLabel: true, left: 12, right: 40, bottom: 12, top: 40 },
      xAxis: { type: "value", max: 100, axisLabel: { formatter: "{value}%" }, splitLine: { show: false } },
      yAxis: { type: "category", data: ["Design", "Backend", "Frontend", "Testing", "Deployment"], inverse: true },
      series: [
        {
          name: "Background",
          type: "bar",
          barWidth: 16,
          data: [100, 100, 100, 100, 100],
          itemStyle: { color: "#dbeafe", borderRadius: 8 },
          barGap: "-100%",
          silent: true,
        },
        {
          name: "Progress",
          type: "bar",
          barWidth: 16,
          data: [92, 78, 65, 45, 30],
          itemStyle: { color: "#3b82f6", borderRadius: 8 },
          label: { show: true, position: "right", formatter: "{c}%", color: "#1d4ed8" },
        },
      ],
    },
  },
  {
    type: "ringProgress",
    label: "Ring Progress",
    description: "Gauge styled as a ring progress indicator",
    option: {
      series: [{
        type: "gauge",
        startAngle: 90,
        endAngle: -270,
        pointer: { show: false },
        progress: { show: true, overlap: false, roundCap: true, clip: false, itemStyle: { color: "#3b82f6" } },
        axisLine: { lineStyle: { width: 20, color: [[1, "#dbeafe"]] } },
        splitLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        title: { show: true, offsetCenter: [0, "30%"], fontSize: 13, color: "#64748b" },
        detail: { valueAnimation: true, fontSize: 32, offsetCenter: [0, "-10%"], formatter: "{value}%", color: "#2563eb" },
        data: [{ value: 68, name: "Completion" }],
      }],
    },
  },
  {
    type: "liquidfill",
    label: "Percentage Gauge",
    description: "Simplified gauge showing a percentage fill",
    option: {
      series: [{
        type: "gauge",
        center: ["50%", "55%"],
        startAngle: 200,
        endAngle: -20,
        min: 0,
        max: 100,
        splitNumber: 10,
        itemStyle: { color: "#3b82f6" },
        progress: { show: true, width: 24 },
        pointer: { show: true, length: "60%", width: 5, itemStyle: { color: "#1d4ed8" } },
        axisLine: { lineStyle: { width: 24, color: [[1, "#dbeafe"]] } },
        axisTick: { distance: -30, splitNumber: 5, lineStyle: { width: 1, color: "#93c5fd" } },
        splitLine: { distance: -36, length: 12, lineStyle: { width: 2, color: "#93c5fd" } },
        axisLabel: { distance: -16, color: "#64748b", fontSize: 10 },
        anchor: { show: true, size: 16, itemStyle: { borderColor: "#2563eb", borderWidth: 3 } },
        title: { show: true, offsetCenter: [0, "75%"], fontSize: 14 },
        detail: { valueAnimation: true, fontSize: 28, offsetCenter: [0, "50%"], formatter: "{value}%", color: "#2563eb" },
        data: [{ value: 82, name: "Capacity" }],
      }],
    },
  },
  {
    type: "timeline-bar",
    label: "Timeline Bar",
    description: "Bar chart showing data across time periods",
    option: {
      title: { text: "Quarterly Revenue by Region", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { containLabel: true, left: 12, right: 12, bottom: 32, top: 40 },
      xAxis: { type: "category", data: ["2022 Q1", "2022 Q2", "2022 Q3", "2022 Q4", "2023 Q1", "2023 Q2", "2023 Q3", "2023 Q4"] },
      yAxis: { type: "value", name: "Revenue ($M)" },
      series: [
        { name: "North", type: "bar", data: [120, 140, 135, 160, 150, 170, 165, 190], color: "#1d4ed8" },
        { name: "South", type: "bar", data: [90, 100, 110, 95, 105, 120, 130, 140], color: "#3b82f6" },
        { name: "West", type: "bar", data: [70, 80, 75, 85, 90, 95, 100, 110], color: "#93c5fd" },
      ],
    },
  },
  {
    type: "negative-bar",
    label: "Positive/Negative Bar",
    description: "Bar chart with values above and below zero",
    option: {
      title: { text: "Profit & Loss by Month", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "category", data: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] },
      yAxis: { type: "value", name: "Profit ($K)" },
      series: [{
        type: "bar",
        data: [25, -12, 34, -8, 42, 18, -5, 30, -15, 22, 38, 45],
        itemStyle: {
          color: (params: { value: number }) => params.value >= 0 ? "#2563eb" : "#93c5fd",
        },
        label: { show: true, position: "top", formatter: "{c}" },
      }],
    },
  },
  {
    type: "slope",
    label: "Slope Chart",
    description: "Two-point comparison showing change between periods",
    option: {
      title: { text: "Market Share Change", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { containLabel: true, left: 40, right: 40, bottom: 32, top: 40 },
      xAxis: { type: "category", data: ["2023", "2024"], boundaryGap: false, axisLine: { lineStyle: { color: "#94a3b8" } } },
      yAxis: { type: "value", name: "Share (%)", min: 0, max: 50 },
      series: [
        { name: "Company A", type: "line", data: [35, 28], color: "#1e40af", lineStyle: { width: 3 }, symbolSize: 10 },
        { name: "Company B", type: "line", data: [22, 30], color: "#2563eb", lineStyle: { width: 3 }, symbolSize: 10 },
        { name: "Company C", type: "line", data: [18, 20], color: "#3b82f6", lineStyle: { width: 3 }, symbolSize: 10 },
        { name: "Company D", type: "line", data: [15, 12], color: "#60a5fa", lineStyle: { width: 3 }, symbolSize: 10 },
        { name: "Company E", type: "line", data: [10, 10], color: "#93c5fd", lineStyle: { width: 3 }, symbolSize: 10 },
      ],
    },
  },
  {
    type: "dumbbell",
    label: "Dumbbell Chart",
    description: "Range comparison between two values per category",
    option: {
      title: { text: "Salary Ranges by Role", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: { containLabel: true, left: 12, right: 12, bottom: 12, top: 40 },
      xAxis: { type: "value", name: "Salary ($K)", min: 40, max: 200 },
      yAxis: { type: "category", data: ["Junior Dev", "Senior Dev", "Tech Lead", "Architect", "VP Eng"], inverse: true },
      series: [
        {
          name: "Range",
          type: "custom",
          renderItem: (_params: unknown, api: { value: (idx: number) => number; coord: (val: [number, number]) => number[]; size: (val: [number, number]) => number[]; style: (opts: Record<string, unknown>) => Record<string, unknown> }) => {
            const categoryIndex = api.value(0);
            const low = api.value(1);
            const high = api.value(2);
            const coordLow = api.coord([low, categoryIndex]);
            const coordHigh = api.coord([high, categoryIndex]);
            const halfHeight = (api.size([0, 1])[1] ?? 0) * 0.1;
            return {
              type: "group",
              children: [
                { type: "line", shape: { x1: coordLow[0], y1: coordLow[1], x2: coordHigh[0], y2: coordHigh[1] }, style: { stroke: "#3b82f6", lineWidth: 3 } },
                { type: "circle", shape: { cx: coordLow[0], cy: coordLow[1], r: halfHeight + 4 }, style: api.style({ fill: "#2563eb" }) },
                { type: "circle", shape: { cx: coordHigh[0], cy: coordHigh[1], r: halfHeight + 4 }, style: api.style({ fill: "#1d4ed8" }) },
              ],
            };
          },
          encode: { x: [1, 2], y: 0 },
          data: [
            [0, 55, 85],
            [1, 85, 135],
            [2, 110, 160],
            [3, 130, 180],
            [4, 150, 200],
          ],
          z: 10,
        },
      ],
    },
  },
  {
    type: "grouped-bar",
    label: "Grouped Bar Chart",
    description: "Side-by-side bars for direct comparison",
    option: {
      title: { text: "Sales by Region & Quarter", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { containLabel: true, left: 12, right: 12, bottom: 32, top: 40 },
      xAxis: { type: "category", data: ["North", "South", "East", "West"] },
      yAxis: { type: "value", name: "Sales ($K)" },
      series: [
        { name: "Q1", type: "bar", data: [320, 280, 350, 190], color: "#1e40af", barGap: "10%" },
        { name: "Q2", type: "bar", data: [380, 310, 290, 240], color: "#2563eb" },
        { name: "Q3", type: "bar", data: [410, 340, 380, 280], color: "#3b82f6" },
        { name: "Q4", type: "bar", data: [450, 390, 420, 310], color: "#60a5fa" },
      ],
    },
  },
  {
    type: "wind-rose",
    label: "Wind Rose",
    description: "Polar stacked bar showing directional distribution",
    option: {
      title: { text: "Wind Rose Diagram", left: "center", textStyle: { fontSize: 14 } },
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      polar: {},
      angleAxis: { type: "category", data: ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"], boundaryGap: false },
      radiusAxis: { min: 0 },
      series: [
        { name: "0-5 m/s", type: "bar", data: [3, 2, 4, 3, 5, 4, 6, 5, 4, 3, 5, 4, 3, 2, 4, 3], coordinateSystem: "polar", stack: "wind", color: "#bfdbfe" },
        { name: "5-10 m/s", type: "bar", data: [2, 3, 3, 2, 4, 3, 5, 4, 3, 2, 4, 3, 2, 1, 3, 2], coordinateSystem: "polar", stack: "wind", color: "#60a5fa" },
        { name: "10-15 m/s", type: "bar", data: [1, 1, 2, 1, 2, 2, 3, 2, 2, 1, 2, 2, 1, 1, 2, 1], coordinateSystem: "polar", stack: "wind", color: "#2563eb" },
        { name: ">15 m/s", type: "bar", data: [0, 0, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 0, 0, 1, 0], coordinateSystem: "polar", stack: "wind", color: "#1e3a8a" },
      ],
    },
  },
];
