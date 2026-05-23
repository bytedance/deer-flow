"use client";

import { GaugeIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import type { ContextUsage } from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

import { formatContextUsagePercentage } from "./context-usage-format";

interface ContextUsageBadgeProps {
  contextUsage: ContextUsage | null;
  className?: string;
}

export function ContextUsageBadge({
  contextUsage,
  className,
}: ContextUsageBadgeProps) {
  const { t } = useI18n();

  const formatted = formatContextUsagePercentage(contextUsage?.percentage);
  if (!formatted) {
    return null;
  }

  return (
    <div
      role="status"
      aria-label={t.contextUsage.badgeAriaLabel(formatted)}
      className={cn(
        "text-muted-foreground bg-background/70 flex h-auto items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-normal",
        className,
      )}
    >
      <GaugeIcon size={14} />
      <span>{t.contextUsage.label}</span>
      <span className="font-mono">{formatted}%</span>
    </div>
  );
}
