"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface ChartBlockProps {
  block: {
    props: {
      chart_type: "bar" | "line" | "pie" | "scatter";
      title?: string;
      subtitle?: string;
      x_key?: string;
      y_key?: string;
      data: Record<string, unknown>[];
      series?: { key: string; label?: string; color?: string }[];
      colors?: string[];
      x_label?: string;
      y_label?: string;
      legend?: boolean;
      stacked?: boolean;
    };
  };
}

const INDUSTRIAL_COLORS = [
  "#10b981", // 正常 - 绿色 (normal/healthy)
  "#f59e0b", // 预警 - 黄色 (warning/caution)
  "#ef4444", // 报警 - 红色 (alarm/critical)
  "#3b82f6", // 信息 - 蓝色 (info/reference)
  "#8b5cf6", // 辅助 - 紫色 (auxiliary/secondary)
  "#06b6d4", // 数据 - 青色 (data/trend)
  "#ec4899", // 标记 - 粉色 (marker/highlight)
  "#84cc16", // 补充 - 黄绿 (supplementary)
  "#f97316", // 警告 - 橙色 (caution/elevated)
  "#6366f1", // 中性 - 靛蓝 (neutral/baseline)
];

const DEFAULT_COLORS = INDUSTRIAL_COLORS;

export default function ChartBlock({ block }: ChartBlockProps) {
  const { props } = block;
  const { chart_type, title, subtitle, data, x_key, y_key, series, colors, legend, stacked } = props;
  const chartColors = colors ?? DEFAULT_COLORS;

  const renderChart = () => {
    switch (chart_type) {
      case "bar":
        return (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            {x_key && <XAxis dataKey={x_key} />}
            <YAxis />
            <Tooltip />
            {legend && <Legend />}
            {series ? (
              series.map((s, i) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label ?? s.key}
                  fill={s.color ?? chartColors[i % chartColors.length]}
                  stackId={stacked ? "stack" : undefined}
                />
              ))
            ) : (
              y_key && <Bar dataKey={y_key} fill={chartColors[0]} />
            )}
          </BarChart>
        );

      case "line":
        return (
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            {x_key && <XAxis dataKey={x_key} />}
            <YAxis />
            <Tooltip />
            {legend && <Legend />}
            {series ? (
              series.map((s, i) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label ?? s.key}
                  stroke={s.color ?? chartColors[i % chartColors.length]}
                />
              ))
            ) : (
              y_key && <Line type="monotone" dataKey={y_key} stroke={chartColors[0]} />
            )}
          </LineChart>
        );

      case "pie":
        return (
          <PieChart>
            <Tooltip />
            {legend && <Legend />}
            <Pie
              data={data}
              dataKey={y_key ?? "value"}
              nameKey={x_key ?? "name"}
              cx="50%"
              cy="50%"
              outerRadius={80}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={chartColors[i % chartColors.length]} />
              ))}
            </Pie>
          </PieChart>
        );

      case "scatter":
        return (
          <ScatterChart>
            <CartesianGrid strokeDasharray="3 3" />
            {x_key && <XAxis dataKey={x_key} name={x_key} />}
            {y_key && <YAxis dataKey={y_key} name={y_key} />}
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            <Scatter data={data} fill={chartColors[0]} />
          </ScatterChart>
        );

      default:
        return null;
    }
  };

  return (
    <div className="rounded-lg border bg-card p-4" role="img" aria-label={title ?? `${chart_type} chart`}>
      {title && <h3 className="mb-1 text-sm font-medium">{title}</h3>}
      {subtitle && <p className="mb-3 text-xs text-muted-foreground">{subtitle}</p>}
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {renderChart() ?? <div />}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
