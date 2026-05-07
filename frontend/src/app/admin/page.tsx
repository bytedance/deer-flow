"use client";

import { useEffect, useState } from "react";

import { AdminScopeBanner } from "@/components/admin/admin-scope-banner";
import { CostChart } from "@/components/admin/cost-chart";
import { StatsCard } from "@/components/admin/stats-card";
import { TokenChart } from "@/components/admin/token-chart";
import { getAdminStats, getAdminUsage } from "@/core/admin/api";
import type { AdminStats, UsageRecord } from "@/core/admin/types";
import { useI18n } from "@/core/i18n/hooks";

export default function AdminDashboardPage() {
  const { t } = useI18n();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdminStats()
      .then(setStats)
      .catch((err: Error) => setError(err.message));
    getAdminUsage()
      .then(setUsage)
      .catch(() => undefined);
  }, []);

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-destructive">{error}</p>
      </div>
    );
  }

  const costData = aggregateCostByDate(usage);
  const tokenData = aggregateTokensByDate(usage);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t.admin.dashboard}</h1>
      <AdminScopeBanner />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title={t.admin.totalTenants}
          value={stats?.total_tenants ?? "-"}
        />
        <StatsCard
          title={t.admin.activeToday}
          value={stats?.active_tenants_today ?? "-"}
        />
        <StatsCard
          title={t.admin.llmCallsToday}
          value={stats?.total_llm_calls_today ?? "-"}
        />
        <StatsCard
          title={t.admin.tokensToday}
          value={stats?.total_tokens_today?.toLocaleString() ?? "-"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatsCard
          title={t.admin.costToday}
          value={`$${(stats?.total_cost_today ?? 0).toFixed(4)}`}
        />
        <StatsCard
          title={t.admin.costThisMonth}
          value={`$${(stats?.total_cost_month ?? 0).toFixed(4)}`}
        />
        <StatsCard
          title={t.admin.totalThreads}
          value={stats?.total_threads ?? "-"}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <CostChart data={costData} />
        <TokenChart data={tokenData} />
      </div>
    </div>
  );
}

function aggregateCostByDate(
  records: UsageRecord[],
): { date: string; cost: number }[] {
  const map = new Map<string, number>();
  for (const r of records) {
    const date = r.timestamp.slice(0, 10);
    map.set(date, (map.get(date) ?? 0) + r.cost_usd);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, cost]) => ({ date, cost }));
}

function aggregateTokensByDate(
  records: UsageRecord[],
): { date: string; tokens: number }[] {
  const map = new Map<string, number>();
  for (const r of records) {
    const date = r.timestamp.slice(0, 10);
    map.set(date, (map.get(date) ?? 0) + r.total_tokens);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, tokens]) => ({ date, tokens }));
}
