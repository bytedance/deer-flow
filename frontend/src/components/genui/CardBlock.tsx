"use client";

import { AlertTriangle, CheckCircle2, XCircleIcon, ArrowDown, ArrowRight, ArrowUp } from "@/components/ui/icons";

interface CardExtra {
  label: string;
  value: string | number;
}

interface CardTrend {
  direction: "up" | "down" | "flat";
  value: string;
}

interface CardBlockProps {
  block: {
    props: {
      title: string;
      // 新格式：状态卡片
      status?: "normal" | "warning" | "critical";
      content?: string;
      extra?: CardExtra[];
      // 旧格式：数值卡片
      value?: string | number;
      subtitle?: string;
      trend?: CardTrend;
      icon?: string;
      color?: string;
    };
  };
}

// 状态样式映射
const statusStyles = {
  normal: {
    bg: "bg-green-50 dark:bg-green-950/30",
    border: "border-green-200 dark:border-green-800",
    text: "text-green-700 dark:text-green-400",
    icon: CheckCircle2,
  },
  warning: {
    bg: "bg-yellow-50 dark:bg-yellow-950/30",
    border: "border-yellow-200 dark:border-yellow-800",
    text: "text-yellow-700 dark:text-yellow-400",
    icon: AlertTriangle,
  },
  critical: {
    bg: "bg-red-50 dark:bg-red-950/30",
    border: "border-red-200 dark:border-red-800",
    text: "text-red-700 dark:text-red-400",
    icon: XCircleIcon,
  },
};

export default function CardBlock({ block }: CardBlockProps) {
  const { props } = block;
  const { title, status, content, extra, value, subtitle, trend } = props;

  // 新格式：状态卡片
  if (status && (content || extra)) {
    const style = statusStyles[status] || statusStyles.normal;
    const StatusIcon = style.icon;
    // LLM 可能传单个对象而非数组，做容错
    const extraItems: CardExtra[] = Array.isArray(extra) ? extra : extra ? [extra] : [];

    return (
      <div
        className={`rounded-lg border ${style.border} ${style.bg} p-4`}
        role="region"
        aria-label={title}
      >
        {/* 标题和状态 */}
        <div className="flex items-center gap-2">
          <StatusIcon className={`h-5 w-5 ${style.text}`} aria-hidden="true" />
          <h3 className="font-medium text-foreground">{title}</h3>
        </div>

        {/* 内容描述 */}
        {content && (
          <p className={`mt-2 text-sm ${style.text}`}>{content}</p>
        )}

        {/* 额外信息 */}
        {extraItems.length > 0 && (
          <div className="mt-3 grid grid-cols-2 gap-2 border-t border-current/10 pt-3 sm:grid-cols-3">
            {extraItems.map((item, idx) => (
              <div key={idx} className="text-xs">
                <span className="text-muted-foreground">{item.label}：</span>
                <span className="font-medium text-foreground">{item.value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // 旧格式：数值卡片
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
