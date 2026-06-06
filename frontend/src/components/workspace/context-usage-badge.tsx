"use client";

import { ChevronDownIcon, GaugeIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { formatTokenCount } from "@/core/messages/usage";
import type { ContextUsage } from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

import { ContextUsageBreakdown } from "./context-usage-breakdown";
import { formatContextUsagePercentage } from "./context-usage-format";

interface ContextUsageBadgeProps {
  contextUsage: ContextUsage | null;
  className?: string;
}

/**
 * Standalone pill shown in the chat header when `token_usage.enabled = false`.
 * The button face shows the percentage (or, when the window is unknown,
 * just the messages-side token count); clicking opens a dropdown with the
 * full per-category breakdown — same content as the dropdown that
 * TokenUsageIndicator embeds when token-usage tracking is on.
 */
export function ContextUsageBadge({
  contextUsage,
  className,
}: ContextUsageBadgeProps) {
  const { t } = useI18n();

  if (!contextUsage || contextUsage.breakdown.length === 0) {
    return null;
  }

  const formatted = formatContextUsagePercentage(contextUsage.percentage);
  const buttonContent =
    formatted != null
      ? `${formatted}%`
      : formatTokenCount(contextUsage.usedTokens);
  const ariaLabel =
    formatted != null
      ? t.contextUsage.badgeAriaLabel(formatted)
      : t.contextUsage.title;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          aria-label={ariaLabel}
          className={cn(
            "text-muted-foreground bg-background/70 hover:bg-background/90 flex h-auto items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-normal",
            className,
          )}
        >
          <GaugeIcon size={14} />
          <span>{t.contextUsage.label}</span>
          <span className="font-mono">{buttonContent}</span>
          <ChevronDownIcon className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="end" className="w-96">
        <DropdownMenuLabel className="sr-only">
          {t.contextUsage.title}
        </DropdownMenuLabel>
        <ContextUsageBreakdown contextUsage={contextUsage} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
