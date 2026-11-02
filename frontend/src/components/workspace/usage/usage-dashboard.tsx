"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { useI18n } from "@/core/i18n/hooks";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { useUsage, useUsageRuns } from "@/core/usage/hooks";
import type { UsagePeriod, UsageRunFilter } from "@/core/usage/types";

import { UsageQueryError } from "./query-error";
import { UsageOverview } from "./usage-overview";
import { UsageRuns } from "./usage-runs";

export function UsageDashboard() {
  const { user } = useAuth();
  const { t, locale } = useI18n();
  const text = t.usage;
  const [period, setPeriod] = useState<UsagePeriod>(7);
  const [page, setPage] = useState(0);
  const [status, setStatus] = useState<UsageRunFilter>("all");
  const timezoneOffsetMinutes = -new Date().getTimezoneOffset();
  const allowed = !!user && hasPermission(user, PERMISSIONS.RUNS_READ);
  const staticMode = isStaticWebsiteOnly();
  const usage = useUsage(
    user?.id,
    period,
    timezoneOffsetMinutes,
    allowed && !staticMode,
  );
  const runs = useUsageRuns(user?.id, page, status, allowed && !staticMode);
  const busy = usage.isFetching || runs.isFetching;

  if (staticMode)
    return (
      <p role="status" className="p-6">
        {text.staticUnavailable}
      </p>
    );
  if (!allowed)
    return (
      <p role="alert" className="p-6">
        {user ? text.forbidden : text.unavailable}
      </p>
    );

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 p-4 pb-12 sm:p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {text.title}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {text.description}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => {
            void usage.refetch();
            void runs.refetch();
          }}
        >
          <RefreshCw
            className={busy ? "size-4 animate-spin" : "size-4"}
            aria-hidden="true"
          />
          {text.refresh}
        </Button>
      </header>
      <p className="text-muted-foreground text-sm">{text.reportingNote}</p>
      <div role="group" aria-label={text.period} className="flex gap-2">
        {([7, 30] as const).map((days) => (
          <Button
            key={days}
            size="sm"
            variant={period === days ? "default" : "outline"}
            aria-pressed={period === days}
            onClick={() => setPeriod(days)}
          >
            {days === 7 ? text.last7Days : text.last30Days}
          </Button>
        ))}
      </div>
      <section aria-label={text.period} aria-busy={usage.isFetching}>
        {usage.isError ? (
          <UsageQueryError
            error={usage.error}
            retry={() => void usage.refetch()}
            text={text}
          />
        ) : usage.data ? (
          <UsageOverview usage={usage.data} locale={locale} text={text} />
        ) : (
          <Loading label={text.loading} />
        )}
      </section>

      <Card>
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">{text.recentRuns}</h2>
            <label className="flex items-center gap-2 text-sm">
              {text.status}
              <select
                className="bg-background rounded-md border px-3 py-2"
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value as UsageRunFilter);
                  setPage(0);
                }}
              >
                <option value="all">{text.allStatuses}</option>
                <option value="error">{text.error}</option>
                <option value="timeout">{text.timeout}</option>
              </select>
            </label>
          </div>
          <p className="text-muted-foreground text-sm">{text.recentRunsHint}</p>
        </CardHeader>
        <CardContent className="space-y-4" aria-busy={runs.isFetching}>
          {runs.isError ? (
            <UsageQueryError
              error={runs.error}
              retry={() => void runs.refetch()}
              text={text}
            />
          ) : runs.data ? (
            <UsageRuns runs={runs.data.runs} locale={locale} text={text} />
          ) : (
            <Loading label={text.loading} />
          )}
          <div className="flex flex-wrap items-center justify-end gap-3 text-sm">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0 || runs.isFetching}
              onClick={() => setPage((value) => Math.max(0, value - 1))}
            >
              {text.previous}
            </Button>
            <span aria-live="polite">{text.page(page + 1)}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={!runs.data?.has_more || runs.isFetching || runs.isError}
              onClick={() => setPage((value) => value + 1)}
            >
              {text.next}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div
      role="status"
      className="text-muted-foreground animate-pulse rounded-xl border p-8 text-sm"
    >
      {label}
    </div>
  );
}
