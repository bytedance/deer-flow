export interface DashboardTheme {
  id: string;
  name: string;
  colors: string[];
  preview: string[]; // 4 preview swatch colors
  background?: string;
  cardBackground?: string;
  textColor?: string;
  mutedColor?: string;
  borderColor?: string;
  tooltipBg?: string;
  tooltipBorder?: string;
  splitLineColor?: string;
}

export const DASHBOARD_THEMES: DashboardTheme[] = [
  {
    id: "default",
    name: "Default",
    colors: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#dbeafe"],
    preview: ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd"],
  },
  {
    id: "ember",
    name: "Ember",
    colors: ["#ea580c", "#f97316", "#fb923c", "#fdba74", "#fed7aa", "#fff7ed"],
    preview: ["#ea580c", "#f97316", "#fb923c", "#fdba74"],
  },
  {
    id: "ultraviolet",
    name: "Ultraviolet",
    colors: ["#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe", "#ede9fe"],
    preview: ["#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd"],
  },
  {
    id: "coral-reef",
    name: "Coral Reef",
    colors: ["#e11d48", "#f43f5e", "#fb7185", "#fda4af", "#fecdd3", "#ffe4e6"],
    preview: ["#e11d48", "#f43f5e", "#fb7185", "#fda4af"],
  },
  {
    id: "retro-wave",
    name: "Retro Wave",
    colors: ["#c026d3", "#d946ef", "#e879f9", "#f0abfc", "#f5d0fe", "#fae8ff"],
    preview: ["#c026d3", "#d946ef", "#e879f9", "#f0abfc"],
  },
  {
    id: "electric-violet",
    name: "Electric Violet",
    colors: ["#6d28d9", "#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe"],
    preview: ["#6d28d9", "#7c3aed", "#8b5cf6", "#a78bfa"],
  },
  {
    id: "aurora",
    name: "Aurora",
    colors: ["#059669", "#10b981", "#34d399", "#6ee7b7", "#a7f3d0", "#d1fae5"],
    preview: ["#059669", "#10b981", "#34d399", "#6ee7b7"],
  },
  {
    id: "tokyo",
    name: "Tokyo",
    colors: ["#0891b2", "#06b6d4", "#22d3ee", "#67e8f9", "#a5f3fc", "#cffafe"],
    preview: ["#0891b2", "#06b6d4", "#22d3ee", "#67e8f9"],
  },
  {
    id: "midnight",
    name: "Midnight",
    colors: ["#1e40af", "#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd"],
    preview: ["#1e40af", "#1d4ed8", "#2563eb", "#3b82f6"],
  },
  {
    id: "sunset",
    name: "Sunset",
    colors: ["#dc2626", "#f97316", "#eab308", "#84cc16", "#06b6d4", "#8b5cf6"],
    preview: ["#dc2626", "#f97316", "#eab308", "#84cc16"],
  },
  {
    id: "forest",
    name: "Forest",
    colors: ["#166534", "#15803d", "#22c55e", "#4ade80", "#86efac", "#bbf7d0"],
    preview: ["#166534", "#15803d", "#22c55e", "#4ade80"],
  },
  {
    id: "ocean",
    name: "Ocean",
    colors: ["#164e63", "#0e7490", "#0891b2", "#06b6d4", "#22d3ee", "#67e8f9"],
    preview: ["#164e63", "#0e7490", "#0891b2", "#06b6d4"],
  },
];

// ── Reactive theme store (works across TipTap node views) ──

let _currentThemeId = "default";
const _listeners = new Set<() => void>();

export function getDashboardTheme(): DashboardTheme {
  return DASHBOARD_THEMES.find((t) => t.id === _currentThemeId) ?? DASHBOARD_THEMES[0]!;
}

export function setDashboardThemeId(id: string) {
  if (_currentThemeId === id) return;
  _currentThemeId = id;
  _listeners.forEach((l) => l());
}

export function subscribeDashboardTheme(listener: () => void): () => void {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
}

export function buildEChartsTheme(theme: DashboardTheme) {
  const muted = theme.mutedColor ?? "#94a3b8";
  const splitLine = theme.splitLineColor ?? "#f1f5f9";

  return {
    color: theme.colors,
    backgroundColor: "transparent",

    textStyle: {
      fontFamily:
        '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
      color: theme.textColor ?? "#475569",
      fontSize: 11,
      fontWeight: 400,
    },

    title: {
      show: false, // We render titles outside ECharts for better styling
    },

    tooltip: {
      backgroundColor: "rgba(255,255,255,0.96)",
      borderColor: "rgba(0,0,0,0.06)",
      borderWidth: 1,
      confine: true,
      textStyle: {
        color: "#1e293b",
        fontSize: 12,
        fontWeight: 500,
      },
      extraCssText: [
        "border-radius: 10px",
        "backdrop-filter: blur(12px)",
        "box-shadow: 0 8px 32px -4px rgba(0,0,0,0.08), 0 4px 8px -2px rgba(0,0,0,0.04)",
        "padding: 10px 14px",
        "max-width: 320px",
        "white-space: normal",
        "line-height: 1.5",
      ].join("; "),
    },

    legend: {
      textStyle: {
        color: muted,
        fontSize: 11,
        fontWeight: 500,
      },
      icon: "circle",
      itemWidth: 7,
      itemHeight: 7,
      itemGap: 20,
    },

    categoryAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: muted,
        fontSize: 10,
        fontWeight: 500,
        margin: 12,
      },
      splitLine: { show: false },
    },

    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: muted,
        fontSize: 10,
        fontWeight: 500,
        margin: 12,
      },
      splitLine: {
        show: true,
        lineStyle: {
          color: splitLine,
          width: 1,
          type: "solid" as const,
        },
      },
    },

    grid: {
      containLabel: true,
      left: 8,
      right: 16,
      bottom: 8,
      top: 12,
    },

    line: {
      smooth: 0.4,
      symbol: "none",
      symbolSize: 4,
      lineStyle: { width: 2.5, cap: "round" as const },
      emphasis: {
        focus: "series",
        lineStyle: { width: 3 },
      },
    },

    bar: {
      barMaxWidth: 28,
      barMinWidth: 4,
      itemStyle: {
        borderRadius: [6, 6, 0, 0],
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 8,
          shadowColor: "rgba(0,0,0,0.08)",
        },
      },
    },

    pie: {
      itemStyle: {
        borderColor: "#ffffff",
        borderWidth: 3,
        borderRadius: 6,
      },
      label: {
        color: "#475569",
        fontSize: 11,
        fontWeight: 500,
      },
      emphasis: {
        scaleSize: 6,
        itemStyle: {
          shadowBlur: 24,
          shadowColor: "rgba(0,0,0,0.1)",
        },
      },
    },

    scatter: {
      symbol: "circle",
      symbolSize: 10,
      itemStyle: { opacity: 0.75, borderColor: "#fff", borderWidth: 1 },
      emphasis: {
        itemStyle: {
          shadowBlur: 12,
          shadowColor: "rgba(0,0,0,0.12)",
          opacity: 1,
        },
      },
    },

    radar: {
      axisLine: { lineStyle: { color: splitLine } },
      splitLine: { lineStyle: { color: splitLine } },
      splitArea: {
        areaStyle: {
          color: ["transparent", `${theme.colors[0]}06`],
        },
      },
    },

    funnel: {
      itemStyle: {
        borderColor: "#fff",
        borderWidth: 2,
      },
    },

    graph: { color: theme.colors },
  };
}
