"use client";

/**
 * IndustrialDashboardBlock — Ultra layer panoramic dashboard layout
 *
 * Arranges equipment health metrics with the health score gauge centered,
 * surrounded by key performance indicators, alarms, and trend data.
 *
 * Props:
 * - healthScore: Primary health index (0-100) displayed in center gauge
 * - metrics: Array of supporting KPIs (temperature, pressure, vibration, etc.)
 * - alarms: Active alarm/warning indicators
 * - trend: Historical health trend data
 */

interface Metric {
  label: string;
  value: number | string;
  unit?: string;
  status?: "normal" | "warning" | "alarm";
  icon?: string;
}

interface Alarm {
  level: "info" | "warning" | "alarm" | "critical";
  message: string;
  timestamp?: string;
}

interface TrendPoint {
  time: string;
  value: number;
}

interface IndustrialDashboardBlockProps {
  block: {
    props: {
      healthScore: number;
      healthScoreThresholds?: {
        warn?: number;
        error?: number;
        critical?: number;
      };
      metrics?: Metric[];
      alarms?: Alarm[];
      trend?: TrendPoint[];
      deviceName?: string;
      lastUpdated?: string;
    };
  };
}

function getStatusColor(status?: Metric["status"]): string {
  switch (status) {
    case "warning":
      return "var(--color-alarm-medium)";
    case "alarm":
      return "var(--color-alarm-high)";
    default:
      return "var(--color-primary)";
  }
}

function getAlarmColor(level: Alarm["level"]): string {
  switch (level) {
    case "info":
      return "var(--color-primary)";
    case "warning":
      return "var(--color-alarm-medium)";
    case "alarm":
      return "var(--color-alarm-high)";
    case "critical":
      return "var(--color-alarm-critical)";
    default:
      return "var(--color-muted-foreground)";
  }
}

export default function IndustrialDashboardBlock({
  block,
}: IndustrialDashboardBlockProps) {
  const { props } = block;
  const {
    healthScore,
    healthScoreThresholds,
    metrics = [],
    alarms = [],
    trend = [],
    deviceName,
    lastUpdated,
  } = props;

  // Calculate health score color based on thresholds
  const scoreColor = (() => {
    if (!healthScoreThresholds) return "var(--color-primary)";
    if (healthScoreThresholds.critical !== undefined && healthScore <= healthScoreThresholds.critical) {
      return "var(--color-alarm-critical)";
    }
    if (healthScoreThresholds.error !== undefined && healthScore <= healthScoreThresholds.error) {
      return "var(--color-alarm-high)";
    }
    if (healthScoreThresholds.warn !== undefined && healthScore <= healthScoreThresholds.warn) {
      return "var(--color-alarm-medium)";
    }
    return "var(--color-primary)";
  })();

  return (
    <div
      className="bg-card text-card-foreground rounded-lg border p-6"
      role="region"
      aria-label={deviceName ?? "Equipment Health Dashboard"}
    >
      {/* Header */}
      {deviceName && (
        <div className="mb-6 border-b pb-4">
          <h2 className="text-foreground text-xl font-semibold">{deviceName}</h2>
          {lastUpdated && (
            <p className="text-muted-foreground mt-1 text-xs">
              Last updated: {lastUpdated}
            </p>
          )}
        </div>
      )}

      {/* Main grid layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left column: Key metrics */}
        <div className="space-y-4">
          <h3 className="text-muted-foreground text-sm font-medium">Key Metrics</h3>
          <div className="space-y-3">
            {metrics.slice(0, 4).map((metric, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-md border p-3"
              >
                <div className="flex-1">
                  <p className="text-muted-foreground text-xs">{metric.label}</p>
                  <p
                    className="text-foreground mt-1 text-lg font-semibold"
                    style={{ color: getStatusColor(metric.status) }}
                  >
                    {metric.value}
                    {metric.unit && (
                      <span className="text-muted-foreground ml-1 text-xs">
                        {metric.unit}
                      </span>
                    )}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Center column: Health score gauge (prominent) */}
        <div className="flex flex-col items-center justify-center">
          <div className="mb-4 text-center">
            <p className="text-muted-foreground text-xs font-medium">Health Score</p>
          </div>
          <div className="relative flex items-center justify-center">
            {/* SVG Gauge */}
            <svg
              viewBox="0 0 160 160"
              width="200"
              height="200"
              className="transform -rotate-90"
              aria-hidden="true"
            >
              {/* Background circle */}
              <circle
                cx="80"
                cy="80"
                r="70"
                stroke="var(--color-muted)"
                strokeWidth="12"
                fill="none"
              />
              {/* Progress circle */}
              <circle
                cx="80"
                cy="80"
                r="70"
                stroke={scoreColor}
                strokeWidth="12"
                fill="none"
                strokeLinecap="round"
                strokeDasharray={`${2 * Math.PI * 70}`}
                strokeDashoffset={`${2 * Math.PI * 70 * (1 - healthScore / 100)}`}
                style={{ transition: "stroke-dashoffset 300ms ease-out" }}
              />
            </svg>
            {/* Score value */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span
                className="text-4xl font-bold"
                style={{ color: scoreColor, fontVariantNumeric: "tabular-nums" }}
              >
                {healthScore}
              </span>
              <span className="text-muted-foreground text-xs">/ 100</span>
            </div>
          </div>
          <p className="text-muted-foreground mt-4 text-center text-xs">
            Overall equipment health index
          </p>
        </div>

        {/* Right column: Alarms and additional metrics */}
        <div className="space-y-4">
          <h3 className="text-muted-foreground text-sm font-medium">Active Alarms</h3>
          <div className="max-h-[200px] space-y-2 overflow-y-auto">
            {alarms.length === 0 ? (
              <p className="text-muted-foreground rounded-md border border-dashed p-3 text-center text-xs">
                No active alarms
              </p>
            ) : (
              alarms.map((alarm, i) => (
                <div
                  key={i}
                  className="rounded-md border p-3"
                  style={{ borderLeftWidth: "3px", borderLeftColor: getAlarmColor(alarm.level) }}
                >
                  <div className="flex items-start gap-2">
                    <span
                      className="mt-0.5 inline-block h-2 w-2 flex-shrink-0 rounded-full"
                      style={{ backgroundColor: getAlarmColor(alarm.level) }}
                    />
                    <div className="flex-1">
                      <p className="text-foreground text-xs">{alarm.message}</p>
                      {alarm.timestamp && (
                        <p className="text-muted-foreground mt-1 text-[10px]">
                          {alarm.timestamp}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Additional metrics if available */}
          {metrics.length > 4 && (
            <>
              <h3 className="text-muted-foreground mt-6 text-sm font-medium">
                Additional Metrics
              </h3>
              <div className="space-y-3">
                {metrics.slice(4, 8).map((metric, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-md border p-3"
                  >
                    <div className="flex-1">
                      <p className="text-muted-foreground text-xs">{metric.label}</p>
                      <p
                        className="text-foreground mt-1 text-lg font-semibold"
                        style={{ color: getStatusColor(metric.status) }}
                      >
                        {metric.value}
                        {metric.unit && (
                          <span className="text-muted-foreground ml-1 text-xs">
                            {metric.unit}
                          </span>
                        )}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Trend section */}
      {trend.length > 0 && (
        <div className="mt-6 border-t pt-6">
          <h3 className="text-muted-foreground mb-4 text-sm font-medium">
            Health Trend (Last 24h)
          </h3>
          <div className="flex h-24 items-end gap-1">
            {trend.map((point, i) => (
              <div
                key={i}
                className="flex-1 rounded-t transition-all hover:opacity-80"
                style={{
                  height: `${(point.value / 100) * 100}%`,
                  backgroundColor:
                    point.value >= 80
                      ? "var(--color-primary)"
                      : point.value >= 60
                        ? "var(--color-alarm-medium)"
                        : "var(--color-alarm-high)",
                  opacity: i === trend.length - 1 ? 1 : 0.6,
                }}
                title={`${point.time}: ${point.value}`}
              />
            ))}
          </div>
          <div className="text-muted-foreground mt-2 flex justify-between text-[10px]">
            <span>{trend[0]?.time}</span>
            <span>{trend[trend.length - 1]?.time}</span>
          </div>
        </div>
      )}
    </div>
  );
}
