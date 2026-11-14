"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { ChevronRightIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { PromptInputButton } from "@/components/ai-elements/prompt-input";
import { useI18n } from "@/core/i18n/hooks";
import {
  contextUsageCategories,
  contextUsageDenominator,
  contextUsageShare,
  withContextUsageWindow,
  type ContextUsageBreakdown,
  type ContextUsageCategory,
  type ContextUsageCategoryKey,
  type ContextUsageSubcategoryKey,
} from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

import {
  formatContextUsagePercentage,
  formatContextUsageTokens,
} from "./context-usage-format";

const RING_SIZE = 16;
const RING_STROKE = 2;
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/**
 * A tiny but non-zero share would otherwise draw a sub-pixel arc that reads as
 * empty. Keeping a small minimum makes "just started" visible; the exact value
 * stays in the accessible label and the popover.
 */
const MIN_ARC_FRACTION = 12 / 360;

/**
 * Segment colours come from the chart tokens so the bar follows the theme in
 * both modes. The order is fixed per category, not per value.
 */
const CATEGORY_COLOR: Record<ContextUsageCategoryKey, string> = {
  systemPrompt: "bg-chart-1",
  tools: "bg-chart-2",
  skills: "bg-chart-3",
  memoryContext: "bg-chart-4",
  conversation: "bg-chart-5",
};

interface ContextUsageRingProps {
  breakdown: ContextUsageBreakdown | null;
  /**
   * The selected model's window. ``undefined`` keeps the window recorded in the
   * snapshot (for example while the model list is loading); ``null`` means the
   * selected model declares no window.
   */
  contextWindow?: number | null;
  /** Selected model name; overrides the name recorded in the snapshot. */
  modelName?: string;
  /** Called when the popover opens, so the caller can refresh the snapshot. */
  onOpen?: () => void;
  className?: string;
}

function formatShare(share: number | null): string | null {
  const formatted = formatContextUsagePercentage(share);
  return formatted == null ? null : `${formatted}%`;
}

function BreakdownRow({
  label,
  tokens,
  denominator,
  colorClassName,
  subcategories,
  expanded,
  onToggle,
}: {
  label: string;
  tokens: number;
  denominator: number;
  colorClassName?: string;
  subcategories?: {
    key: ContextUsageSubcategoryKey;
    label: string;
    tokens: number;
  }[];
  expanded?: boolean;
  onToggle?: () => void;
}) {
  const share = formatShare(contextUsageShare(tokens, denominator));
  const row = (
    <>
      <span className="flex min-w-0 items-center gap-1.5">
        {colorClassName ? (
          <span
            aria-hidden="true"
            className={cn("size-2 shrink-0 rounded-[2px]", colorClassName)}
          />
        ) : (
          <span aria-hidden="true" className="size-2 shrink-0" />
        )}
        <span className="truncate">{label}</span>
        {subcategories && (
          <ChevronRightIcon
            aria-hidden="true"
            className={cn(
              "text-muted-foreground size-3 shrink-0 transition-transform",
              expanded && "rotate-90",
            )}
          />
        )}
      </span>
      <span className="text-muted-foreground shrink-0 font-mono tabular-nums">
        {formatContextUsageTokens(tokens)}
        {share ? ` · ${share}` : ""}
      </span>
    </>
  );

  if (!subcategories) {
    return (
      <div className="flex items-center justify-between gap-3 py-0.5 text-xs">
        {row}
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="hover:bg-accent/60 flex w-full cursor-pointer items-center justify-between gap-3 rounded-sm py-0.5 text-left text-xs"
      >
        {row}
      </button>
      {expanded && (
        <div className="border-border/60 mt-0.5 mb-1 ml-3.5 space-y-0.5 border-l pl-3">
          {subcategories.map((subcategory) => (
            <BreakdownRow
              key={subcategory.key}
              label={subcategory.label}
              tokens={subcategory.tokens}
              denominator={denominator}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ContextUsageBar({
  categories,
  denominator,
}: {
  categories: ContextUsageCategory[];
  denominator: number;
}) {
  // Keep the segments inside the track even when the request exceeds the
  // declared window; the percentage text still reports the overage.
  const barDenominator = Math.max(
    denominator,
    categories.reduce((total, category) => total + category.tokens, 0),
    1,
  );
  return (
    <div
      aria-hidden="true"
      className="bg-muted flex h-2 w-full overflow-hidden rounded-full"
    >
      {categories.map((category) =>
        category.tokens > 0 ? (
          <div
            key={category.key}
            className={cn("h-full", CATEGORY_COLOR[category.key])}
            style={{ width: `${(category.tokens / barDenominator) * 100}%` }}
          />
        ) : null,
      )}
    </div>
  );
}

export function ContextUsageRing({
  breakdown,
  contextWindow,
  modelName,
  onOpen,
  className,
}: ContextUsageRingProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<
    Partial<Record<ContextUsageCategoryKey, boolean>>
  >({});

  // The snapshot belongs to the last model call; the selected model may have a
  // different window before the next call.
  const effectiveBreakdown = useMemo(
    () => (breakdown ? withContextUsageWindow(breakdown, contextWindow) : null),
    [breakdown, contextWindow],
  );

  const effectiveWindow = effectiveBreakdown
    ? effectiveBreakdown.contextWindow
    : contextWindow != null && contextWindow > 0
      ? contextWindow
      : null;
  const hasWindow = Boolean(effectiveWindow && effectiveWindow > 0);
  // Before the first snapshot the selected model still decides the track: a
  // solid light circle when it declares a window, a light dashed one otherwise.
  // A dashed track turns dark only once there is composition data to show.
  const trackClassName =
    !hasWindow && effectiveBreakdown ? "text-primary" : "text-border";
  const percentage = formatContextUsagePercentage(
    effectiveBreakdown?.percentage,
  );
  const ariaLabel = effectiveBreakdown
    ? hasWindow
      ? t.contextUsage.ringAriaLabel(percentage ?? "0")
      : t.contextUsage.ringAriaLabelNoWindow(
          formatContextUsageTokens(effectiveBreakdown.totalTokens),
        )
    : t.contextUsage.ringAriaLabelEmpty;

  const fraction =
    effectiveBreakdown && effectiveWindow
      ? Math.min(1, effectiveBreakdown.totalTokens / effectiveWindow)
      : null;
  const arcFraction =
    fraction != null && fraction > 0
      ? Math.max(fraction, MIN_ARC_FRACTION)
      : null;

  const categories = useMemo(
    () =>
      effectiveBreakdown ? contextUsageCategories(effectiveBreakdown) : [],
    [effectiveBreakdown],
  );
  const denominator = effectiveBreakdown
    ? contextUsageDenominator(effectiveBreakdown)
    : 0;
  const categoryLabels: Record<ContextUsageCategoryKey, string> = {
    systemPrompt: t.contextUsage.categories.systemPrompt,
    tools: t.contextUsage.categories.tools,
    skills: t.contextUsage.categories.skills,
    memoryContext: t.contextUsage.categories.memoryContext,
    conversation: t.contextUsage.categories.conversation,
  };
  const subcategoryLabels: Record<ContextUsageSubcategoryKey, string> = {
    builtinTools: t.contextUsage.subcategories.builtinTools,
    mcpTools: t.contextUsage.subcategories.mcpTools,
    memory: t.contextUsage.subcategories.memory,
    taskState: t.contextUsage.subcategories.taskState,
    otherInjection: t.contextUsage.subcategories.otherInjection,
    conversationMessages: t.contextUsage.subcategories.conversationMessages,
    toolResults: t.contextUsage.subcategories.toolResults,
  };

  const hasRemaining =
    effectiveBreakdown != null &&
    hasWindow &&
    effectiveBreakdown.remainingTokens != null;
  const displayModelName = modelName ?? effectiveBreakdown?.modelName;

  return (
    <PopoverPrimitive.Root
      onOpenChange={(open) => {
        if (open) {
          onOpen?.();
        }
      }}
    >
      <PopoverPrimitive.Trigger asChild>
        <PromptInputButton
          aria-label={ariaLabel}
          title={ariaLabel}
          data-testid="context-usage-ring"
          data-context-usage-state={
            !effectiveBreakdown ? "empty" : hasWindow ? "window" : "used-only"
          }
          className={cn("size-8 shrink-0 p-0", className)}
        >
          <svg
            aria-hidden="true"
            viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
            className="size-3.5"
          >
            <circle
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={RING_RADIUS}
              fill="none"
              stroke="currentColor"
              strokeWidth={RING_STROKE}
              strokeDasharray={hasWindow ? undefined : "2 3"}
              className={trackClassName}
            />
            {arcFraction != null && (
              <circle
                cx={RING_SIZE / 2}
                cy={RING_SIZE / 2}
                r={RING_RADIUS}
                fill="none"
                stroke="currentColor"
                strokeWidth={RING_STROKE}
                strokeLinecap="round"
                strokeDasharray={`${arcFraction * RING_CIRCUMFERENCE} ${RING_CIRCUMFERENCE}`}
                transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
                className="text-primary"
              />
            )}
          </svg>
        </PromptInputButton>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="top"
          align="end"
          sideOffset={8}
          aria-label={t.contextUsage.breakdownTitle}
          data-testid="context-usage-popover"
          className="bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 z-50 w-80 max-w-[calc(100vw-2rem)] origin-(--radix-popover-content-transform-origin) rounded-lg border p-3 shadow-lg outline-none"
        >
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium">
              {t.contextUsage.breakdownTitle}
            </span>
            {displayModelName && (
              <span className="text-muted-foreground truncate font-mono text-[10px]">
                {displayModelName}
              </span>
            )}
          </div>
          {effectiveBreakdown ? (
            <div className="space-y-2">
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span className="font-mono tabular-nums">
                  {hasWindow
                    ? t.contextUsage.usedOfWindow(
                        formatContextUsageTokens(
                          effectiveBreakdown.totalTokens,
                        ),
                        formatContextUsageTokens(
                          effectiveBreakdown.contextWindow ?? 0,
                        ),
                      )
                    : t.contextUsage.usedOnly(
                        formatContextUsageTokens(
                          effectiveBreakdown.totalTokens,
                        ),
                      )}
                </span>
                {percentage != null && (
                  <span className="font-mono font-medium tabular-nums">
                    {percentage}%
                  </span>
                )}
              </div>
              <ContextUsageBar
                categories={categories}
                denominator={denominator}
              />
              <div className="text-muted-foreground flex items-center justify-between gap-2 text-[10px]">
                <span>
                  {hasWindow
                    ? t.contextUsage.shareOfWindow
                    : t.contextUsage.shareOfUsed}
                </span>
                {hasRemaining && (
                  <span className="font-mono tabular-nums">
                    {t.contextUsage.remaining(
                      formatContextUsageTokens(
                        effectiveBreakdown.remainingTokens ?? 0,
                      ),
                    )}
                  </span>
                )}
              </div>
              <div className="border-border/60 space-y-0.5 border-t pt-1.5">
                {categories.map((category) => (
                  <BreakdownRow
                    key={category.key}
                    label={categoryLabels[category.key]}
                    tokens={category.tokens}
                    denominator={denominator}
                    colorClassName={CATEGORY_COLOR[category.key]}
                    subcategories={
                      category.subcategories.length > 0
                        ? category.subcategories.map((subcategory) => ({
                            key: subcategory.key,
                            label: subcategoryLabels[subcategory.key],
                            tokens: subcategory.tokens,
                          }))
                        : undefined
                    }
                    expanded={expanded[category.key] === true}
                    onToggle={() =>
                      setExpanded((current) => ({
                        ...current,
                        [category.key]: current[category.key] !== true,
                      }))
                    }
                  />
                ))}
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground text-xs leading-relaxed">
              {t.contextUsage.empty}
            </p>
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
