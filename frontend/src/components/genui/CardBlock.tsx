"use client";

import { ArrowDown, ArrowRight, ArrowUp } from "@/components/ui/icons";

interface CardBlockProps {
  block: {
    props: {
      title: string;
      value: string | number;
      subtitle?: string;
      trend?: {
        direction: "up" | "down" | "flat";
        value: string;
      };
      icon?: string;
      color?: string;
    };
  };
}

export default function CardBlock({ block }: CardBlockProps) {
  const { props } = block;
  const { title, value, subtitle, trend } = props;

  const trendColor =
    trend?.direction === "up"
      ? "text-green-600 dark:text-green-400"
      : trend?.direction === "down"
        ? "text-red-600 dark:text-red-400"
        : "text-muted-foreground";

  const TrendIcon =
    trend?.direction === "up"
      ? ArrowUp
      : trend?.direction === "down"
        ? ArrowDown
        : ArrowRight;

  return (
    <div className="rounded-xl bg-muted/30 p-4" role="region" aria-label={title}>
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold">{value}</span>
        {trend && (
          <span className={`flex items-center gap-0.5 text-xs ${trendColor}`} aria-label={`Trend ${trend.direction} ${trend.value}`}>
            <TrendIcon className="h-3 w-3" aria-hidden="true" />
            {trend.value}
          </span>
        )}
      </div>
      {subtitle && (
        <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
      )}
    </div>
  );
}
