"use client";

/**
 * MetricBlock — engineering readout for a single tag/measurement: current
 * value, unit, optional setpoint and range bounds (LL/L/H/HH), plus an
 * optional delta against a previous period.
 *
 * Numeric formatting is locked to tabular-nums so columns of values align
 * across rows. Backend skills decide units, precision, and ranges; the
 * frontend just renders.
 */

import {
  ArrowDownIcon,
  ArrowRightIcon,
  ArrowUpIcon,
} from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";

type MetricStatus =
  | "running"
  | "stopped"
  | "maint"
  | "standby"
  | "fault"
  | "comm-loss";

interface MetricRange {
  ll?: number;
  l?: number;
  h?: number;
  hh?: number;
}

interface MetricDelta {
  value: number | string;
  direction?: "up" | "down" | "flat";
  vs?: string;
}

interface MetricBlockProps {
  block: {
    props: {
      tag?: string;
      label?: string;
      value: number | string;
      unit?: string;
      precision?: number;
      setpoint?: number;
      range?: MetricRange;
      delta?: MetricDelta;
      status?: MetricStatus;
    };
  };
}

function formatValue(
  value: number | string,
  precision: number | undefined,
): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(precision ?? 2);
  }
  return String(value);
}

function deltaTone(direction?: "up" | "down" | "flat"): {
  cls: string;
  Icon: typeof ArrowUpIcon;
} {
  if (direction === "up") {
    return {
      cls: "text-status-running",
      Icon: ArrowUpIcon,
    };
  }
  if (direction === "down") {
    return {
      cls: "text-alarm-high",
      Icon: ArrowDownIcon,
    };
  }
  return {
    cls: "text-muted-foreground",
    Icon: ArrowRightIcon,
  };
}

export default function MetricBlock({ block }: MetricBlockProps) {
  const { t } = useI18n();
  const { props } = block;
  const display = formatValue(props.value, props.precision);
  const { cls: deltaCls, Icon: DeltaIcon } = deltaTone(props.delta?.direction);

  return (
    <div
      className="bg-card text-card-foreground flex flex-col gap-1 rounded-lg border p-4"
      role="region"
      aria-label={props.label ?? props.tag ?? "metric"}
    >
      {(props.tag ?? props.label) && (
        <div className="flex items-baseline justify-between gap-2">
          {props.tag && (
            <span
              className="text-muted-foreground font-mono text-xs"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {props.tag}
            </span>
          )}
          {props.label && (
            <span className="text-muted-foreground truncate text-xs">
              {props.label}
            </span>
          )}
        </div>
      )}
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
      {props.delta && (
        <div
          className={`inline-flex items-center gap-0.5 text-xs ${deltaCls}`}
          aria-label={`${t.genui.ariaDeviation} ${props.delta.direction ?? "flat"} ${props.delta.value}`}
        >
          <DeltaIcon className="size-3" aria-hidden="true" />
          <span style={{ fontVariantNumeric: "tabular-nums" }}>
            {props.delta.value}
          </span>
          {props.delta.vs && (
            <span className="text-muted-foreground ml-1">
              vs {props.delta.vs}
            </span>
          )}
        </div>
      )}
      {(props.setpoint !== undefined || props.range) && (
        <div
          className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {props.setpoint !== undefined && (
            <span aria-label={t.genui.ariaSetpoint}>
              SP {formatValue(props.setpoint, props.precision)}
            </span>
          )}
          {props.range?.ll !== undefined && (
            <span aria-label={t.genui.ariaLowLowLimit}>
              LL {formatValue(props.range.ll, props.precision)}
            </span>
          )}
          {props.range?.l !== undefined && (
            <span aria-label={t.genui.ariaLowLimit}>
              L {formatValue(props.range.l, props.precision)}
            </span>
          )}
          {props.range?.h !== undefined && (
            <span aria-label={t.genui.ariaHighLimit}>
              H {formatValue(props.range.h, props.precision)}
            </span>
          )}
          {props.range?.hh !== undefined && (
            <span aria-label={t.genui.ariaHighHighLimit}>
              HH {formatValue(props.range.hh, props.precision)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
