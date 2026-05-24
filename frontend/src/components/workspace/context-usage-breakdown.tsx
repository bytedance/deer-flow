"use client";

import { useI18n } from "@/core/i18n/hooks";
import { formatTokenCount } from "@/core/messages/usage";
import type {
  ContextUsage,
  ContextUsageBreakdownItem,
} from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

import { ContextUsageBar, breakdownToSegments } from "./context-usage-bar";
import { formatContextUsagePercentage } from "./context-usage-format";

interface ContextUsageBreakdownProps {
  contextUsage: ContextUsage;
  className?: string;
}

/**
 * The "Context window" section that goes inside the TokenUsageIndicator
 * dropdown (and inside the standalone ContextUsageBadge popover). Renders a
 * Claude-Code-style header (`277.2k / 1.0M (28%)`), a multi-segment progress
 * bar, and a per-category table.
 *
 * Categories arrive pre-filtered (zero-token rows are dropped by the backend),
 * so this component just maps each row to its localized label and renders.
 */
export function ContextUsageBreakdown({
  contextUsage,
  className,
}: ContextUsageBreakdownProps) {
  const { t } = useI18n();

  const categoryLabels = t.contextUsage.categories as Record<string, string>;
  const labelForRow = (row: ContextUsageBreakdownItem) =>
    categoryLabels[row.key] ?? row.key;

  // Compute the segments and the breakdown total inline — they're cheap (O(n)
  // over a handful of rows) and depending on `categoryLabels` directly in a
  // useMemo would force a recompute on every locale change anyway. Keeping it
  // unmemoized avoids the easy footgun of stale tooltips when the user
  // switches language (the original useMemo deps omitted `t`).
  const totalTokens = contextUsage.breakdown.reduce(
    (sum, row) => sum + row.tokens,
    0,
  );
  const denominator = contextUsage.maxContextTokens ?? totalTokens;
  const percentageText = formatContextUsagePercentage(contextUsage.percentage);
  const segments = breakdownToSegments(
    contextUsage.breakdown,
    denominator,
    labelForRow,
  );

  return (
    <div className={cn("space-y-2 px-2 py-1 text-xs", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-muted-foreground">{t.contextUsage.title}</span>
        <span className="font-mono">
          {contextUsage.maxContextTokens && percentageText
            ? t.contextUsage.summary(
                formatTokenCount(contextUsage.usedTokens),
                formatTokenCount(contextUsage.maxContextTokens),
                percentageText,
              )
            : formatTokenCount(contextUsage.usedTokens)}
        </span>
      </div>

      {segments.length > 0 && <ContextUsageBar segments={segments} />}

      <ul className="space-y-0.5">
        {contextUsage.breakdown.map((row) => {
          const rowPercent =
            denominator > 0 ? (row.tokens / denominator) * 100 : null;
          return (
            <li
              key={row.key}
              className={cn(
                "flex items-baseline justify-between gap-3",
                !row.active && "text-muted-foreground",
              )}
            >
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className={cn(
                    "inline-block size-2 rounded-sm",
                    row.active ? "bg-primary/80" : "bg-muted-foreground/40",
                  )}
                />
                {labelForRow(row)}
              </span>
              <span className="text-muted-foreground/80 flex items-baseline gap-3 font-mono tabular-nums">
                <span>{formatTokenCount(row.tokens)}</span>
                {rowPercent != null && (
                  <span className="text-muted-foreground/60 w-12 text-right">
                    {rowPercent < 0.05 ? "0.0%" : `${rowPercent.toFixed(1)}%`}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>

      {contextUsage.maxContextTokens == null && (
        <div className="text-muted-foreground pt-1 leading-relaxed">
          {t.contextUsage.capacityUnknown}
        </div>
      )}
    </div>
  );
}
