"use client";

import { AlertTriangleIcon, CoinsIcon } from "lucide-react";

import { Progress } from "@/components/ui/progress";
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

export function BudgetSettingsPage() {
  const { t } = useI18n();
  const { data: budget, isLoading, error } = useBudgetStatus();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">{t.budget.todayUsage}</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {t.budget.thisMonth}
        </p>
      </div>

      {isLoading && (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      )}

      {error && (
        <div className="text-sm text-destructive">Failed to load budget data.</div>
      )}

      {budget && (
        <div className="space-y-4">
          <div className="rounded-lg border p-4 space-y-3">
            <h3 className="text-sm font-medium">{t.budget.today}</h3>
            <div className="flex items-center justify-between gap-4 text-sm">
              <span className="text-muted-foreground">
                {t.budget.used} {formatCurrency(budget.daily_cost)} {t.budget.of} {formatCurrency(budget.daily_limit)}
              </span>
              <span className="text-muted-foreground">
                {t.budget.remaining} {formatCurrency(budget.daily_remaining)}
              </span>
            </div>
            <Progress
              value={Math.min(100, budget.daily_pct)}
              className={cn("h-2", getProgressColor(Math.min(100, budget.daily_pct)))}
            />
          </div>

          <div className="rounded-lg border p-4 space-y-3">
            <h3 className="text-sm font-medium">{t.budget.thisMonth}</h3>
            <div className="flex items-center justify-between gap-4 text-sm">
              <span className="text-muted-foreground">
                {t.budget.used} {formatCurrency(budget.monthly_cost)} {t.budget.of} {formatCurrency(budget.monthly_limit)}
              </span>
              <span className="text-muted-foreground">
                {t.budget.remaining} {formatCurrency(budget.monthly_remaining)}
              </span>
            </div>
            <Progress
              value={Math.min(100, budget.monthly_pct)}
              className={cn("h-2", getProgressColor(Math.min(100, budget.monthly_pct)))}
            />
          </div>

          {budget.is_exceeded && (
            <div className="flex items-start gap-2 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertTriangleIcon className="size-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">{t.budget.limitReached}</p>
                <p className="text-muted-foreground">{t.budget.contactAdmin}</p>
              </div>
            </div>
          )}

          {budget.alert_triggered && !budget.is_exceeded && (
            <div className="flex items-start gap-2 rounded-lg border border-warning/50 bg-warning/5 p-3 text-sm text-warning">
              <AlertTriangleIcon className="size-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">{t.budget.warning}</p>
                <p className="text-muted-foreground">{t.budget.approachingLimit}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
