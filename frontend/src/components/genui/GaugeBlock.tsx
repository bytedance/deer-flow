"use client";

/**
 * GaugeBlock — half-circle gauge for engineering readouts (health index,
 * vibration RMS, bearing temp, …). The fill color follows alarm thresholds:
 * `value < warn` → primary, `value < error` → alarm-medium,
 * `value < critical` → alarm-high, otherwise → alarm-critical.
 *
 * Designed for skill output. Backend skills emit this block; the frontend
 * does not own the data semantics.
 */

interface GaugeThresholds {
  warn?: number;
  error?: number;
  critical?: number;
}

interface GaugeBlockProps {
  block: {
    props: {
      value: number;
      min?: number;
      max?: number;
      unit?: string;
      label?: string;
      thresholds?: GaugeThresholds;
      precision?: number;
    };
  };
}

function pickColor(value: number, t?: GaugeThresholds): string {
  if (!t) return "var(--color-primary)";
  if (t.critical !== undefined && value >= t.critical) {
    return "var(--color-alarm-critical)";
  }
  if (t.error !== undefined && value >= t.error) {
    return "var(--color-alarm-high)";
  }
  if (t.warn !== undefined && value >= t.warn) {
    return "var(--color-alarm-medium)";
  }
  return "var(--color-primary)";
}

export default function GaugeBlock({ block }: GaugeBlockProps) {
  const { props } = block;
  const min = props.min ?? 0;
  const max = props.max ?? 100;
  const safeMax = max > min ? max : min + 1;
  const clamped = Math.min(Math.max(props.value, min), safeMax);
  const ratio = (clamped - min) / (safeMax - min);
  const color = pickColor(props.value, props.thresholds);
  const precision = props.precision ?? 2;
  const display =
    typeof props.value === "number" && Number.isFinite(props.value)
      ? props.value.toFixed(precision)
      : "—";

  // SVG arc: 180° semicircle, radius 60, stroke 12.
  const radius = 60;
  const circumference = Math.PI * radius;
  const offset = circumference * (1 - ratio);

  return (
    <div
      className="bg-card text-card-foreground flex flex-col items-center gap-2 rounded-lg border p-4"
      role="region"
      aria-label={props.label ?? "gauge"}
    >
      <svg
        viewBox="0 0 160 90"
        width="100%"
        className="max-w-[200px]"
        aria-hidden="true"
      >
        <path
          d="M 20 80 A 60 60 0 0 1 140 80"
          stroke="var(--color-muted)"
          strokeWidth="12"
          fill="none"
          strokeLinecap="round"
        />
        <path
          d="M 20 80 A 60 60 0 0 1 140 80"
          stroke={color}
          strokeWidth="12"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 200ms ease-out" }}
        />
      </svg>
      <div className="flex items-baseline gap-1">
        <span
          className="text-foreground text-2xl font-semibold"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {display}
        </span>
        {props.unit && (
          <span className="text-muted-foreground text-xs">{props.unit}</span>
        )}
      </div>
      {props.label && (
        <p className="text-muted-foreground text-xs">{props.label}</p>
      )}
      <div className="text-muted-foreground flex w-full justify-between text-[10px]">
        <span style={{ fontVariantNumeric: "tabular-nums" }}>{min}</span>
        <span style={{ fontVariantNumeric: "tabular-nums" }}>{safeMax}</span>
      </div>
    </div>
  );
}
