/**
 * ECharts theme adapted for the DeerFlow design system.
 * Uses Tailwind / shadcn-compatible color values.
 */
export const chartTheme = {
  color: [
    "#2563eb",
    "#3b82f6",
    "#60a5fa",
    "#93c5fd",
    "#bfdbfe",
    "#dbeafe",
  ],

  backgroundColor: "transparent",

  textStyle: {
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    color: "#334155",
    fontSize: 12,
  },

  title: {
    textStyle: {
      color: "#1e293b",
      fontSize: 14,
      fontWeight: 600,
    },
    subtextStyle: {
      color: "#64748b",
      fontSize: 12,
    },
  },

  tooltip: {
    backgroundColor: "#ffffff",
    borderColor: "#e2e8f0",
    borderWidth: 1,
    confine: true,
    textStyle: {
      color: "#334155",
      fontSize: 12,
    },
    extraCssText:
      "border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.05); max-width: 350px; white-space: normal;",
  },

  legend: {
    textStyle: {
      color: "#64748b",
      fontSize: 12,
    },
    icon: "circle",
    itemWidth: 8,
    itemHeight: 8,
    itemGap: 16,
  },

  categoryAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: "#64748b",
      fontSize: 11,
    },
    splitLine: {
      show: false,
    },
  },

  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: "#64748b",
      fontSize: 11,
    },
    splitLine: {
      show: true,
      lineStyle: {
        color: "#e2e8f0",
        type: "dashed" as const,
      },
    },
  },

  line: {
    smooth: true,
    symbol: "circle",
    symbolSize: 6,
    lineStyle: {
      width: 2.5,
    },
    areaStyle: {
      opacity: 0.15,
    },
  },

  bar: {
    barMaxWidth: 32,
    itemStyle: {
      borderRadius: [4, 4, 0, 0],
    },
  },

  pie: {
    itemStyle: {
      borderColor: "#ffffff",
      borderWidth: 2,
      borderRadius: 4,
    },
    label: {
      color: "#334155",
      fontSize: 12,
    },
  },

  scatter: {
    symbol: "circle",
    symbolSize: 8,
    itemStyle: {
      opacity: 0.8,
    },
  },

  radar: {
    axisLine: {
      lineStyle: {
        color: "#e2e8f0",
      },
    },
    splitLine: {
      lineStyle: {
        color: "#e2e8f0",
      },
    },
    splitArea: {
      areaStyle: {
        color: ["transparent", "rgba(37, 99, 235, 0.02)"],
      },
    },
  },

  graph: {
    color: [
      "#2563eb",
      "#3b82f6",
      "#60a5fa",
      "#93c5fd",
      "#bfdbfe",
      "#dbeafe",
    ],
  },
};
