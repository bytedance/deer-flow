"use client";

import { CoinsIcon, AlertTriangleIcon } from "lucide-react";

import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useBudgetStatus } from "@/core/cost/use-budget-status";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

function getProgressColor(pct: number): string {
  if (pct >= 95) return "bg-destructive";
  if (pct >= 80) return "bg-warning";
  return "bg-success";
}

function formatCurrency(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function BudgetIndicator() {
  const { t } = useI18n();
  const { data: budget, isLoading, error } = useBudgetStatus();

  if (isLoading || error || !budget) {
    return null;
  }

  const dailyPct = Math.min(100, budget.daily_pct);
  const monthlyPct = Math.min(100, budget.monthly_pct);
  const isWarning = budget.alert_triggered && !budget.is_exceeded;
  const isCritical = budget.is_exceeded;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={cn(
              "mx-2 mb-2 cursor-pointer rounded-lg border p-3 transition-colors",
              isCritical && "border-destructive/50 bg-destructive/5",
              isWarning && "border-warning/50 bg-warning/5",
              !isCritical && !isWarning && "border-border bg-muted/30"
            )}
          >
            <div className="flex items-center gap-2 text-xs">
              {isCritical || isWarning ? (
                <AlertTriangleIcon
                  className={cn(
                    "size-4 shrink-0",
                    isCritical ? "text-destructive" : "text-warning"
                  )}
                />
              ) : (
                <CoinsIcon className="size-4 shrink-0 text-muted-foreground" />
              )}
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="font-medium truncate">
                    {t.budget.today}
                  </span>
                  <span className="text-muted-foreground shrink-0">
                    {formatCurrency(budget.daily_cost)} / {formatCurrency(budget.daily_limit)}
                  </span>
                </div>
                <Progress
                  value={dailyPct}
                  className={cn("h-1.5", getProgressColor(dailyPct))}
                />
              </div>
            </div>

            <div className="mt-2 text-xs">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-muted-foreground truncate">
                  {t.budget.thisMonth}
                </span>
                <span className="text-muted-foreground shrink-0">
                  {formatCurrency(budget.monthly_cost)} / {formatCurrency(budget.monthly_limit)}
                </span>
              </div>
              <Progress
                value={monthlyPct}
                className={cn("h-1", getProgressColor(monthlyPct))}
              />
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-xs">
          <div className="space-y-2 text-xs">
            <div>
              <div className="font-medium">{t.budget.todayUsage}</div>
              <div className="text-muted-foreground">
                {t.budget.used} {formatCurrency(budget.daily_cost)}{" "}
                {t.budget.of} {formatCurrency(budget.daily_limit)}
              </div>
              <div className="text-muted-foreground">
                {t.budget.remaining} {formatCurrency(budget.daily_remaining)}
              </div>
            </div>
            <div className="border-t pt-2">
              <div className="font-medium">{t.budget.monthlyUsage}</div>
              <div className="text-muted-foreground">
                {t.budget.used} {formatCurrency(budget.monthly_cost)}{" "}
                {t.budget.of} {formatCurrency(budget.monthly_limit)}
              </div>
              <div className="text-muted-foreground">
                {t.budget.remaining} {formatCurrency(budget.monthly_remaining)}
              </div>
            </div>
            {isWarning && (
              <div className="border-t pt-2 text-warning">
                <div className="flex items-center gap-1">
                  <AlertTriangleIcon className="size-3" />
                  <span className="font-medium">{t.budget.warning}</span>
                </div>
                <div className="text-muted-foreground">
                  {t.budget.approachingLimit}
                </div>
              </div>
            )}
            {isCritical && (
              <div className="border-t pt-2 text-destructive">
                <div className="flex items-center gap-1">
                  <AlertTriangleIcon className="size-3" />
                  <span className="font-medium">{t.budget.limitReached}</span>
                </div>
                <div className="text-muted-foreground">
                  {t.budget.contactAdmin}
                </div>
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
