"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Play, Power } from "lucide-react";

import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TodoCounts {
  anomalyPending: number;
  startupPending: number;
  shutdownPending: number;
}

// ---------------------------------------------------------------------------
// Indicator
// ---------------------------------------------------------------------------

export function TodoCountIndicator() {
  const { t } = useI18n();
  const [counts, setCounts] = useState<TodoCounts | null>(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    try {
      const res = await fetchGateway(
        `${getBackendBaseURL()}/api/workbench/todo-stats`,
      );
      if (res.ok) {
        const data = (await res.json()) as TodoCounts;
        setCounts(data);
      }
    } catch (err) {
      console.warn("[TodoCountIndicator] fetch failed", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 60_000);
    return () => clearInterval(interval);
  }, [fetch]);

  return (
    <div className="flex items-center gap-1">
      <CountBadge
        icon={<AlertTriangle className="size-3" />}
        label={t.todoCounts.anomalyPending}
        count={counts?.anomalyPending}
        loading={loading}
        intent="warning"
      />
      <CountBadge
        icon={<Play className="size-3" />}
        label={t.todoCounts.startupPending}
        count={counts?.startupPending}
        loading={loading}
        intent="info"
      />
      <CountBadge
        icon={<Power className="size-3" />}
        label={t.todoCounts.shutdownPending}
        count={counts?.shutdownPending}
        loading={loading}
        intent="neutral"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

interface CountBadgeProps {
  icon: React.ReactNode;
  label: string;
  count: number | undefined;
  loading: boolean;
  intent: "warning" | "info" | "neutral";
}

const intentStyles: Record<CountBadgeProps["intent"], string> = {
  warning:
    "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-400",
  info: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-400",
  neutral:
    "border-gray-200 bg-gray-50 text-gray-600 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400",
};

function CountBadge({ icon, label, count, loading, intent }: CountBadgeProps) {
  const { t } = useI18n();
  const hasData = count !== undefined;

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-xs font-medium",
        intentStyles[intent],
      )}
      title={label}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
      <span
        className={cn(
          "tabular-nums font-semibold",
          loading && "animate-pulse",
          !hasData && !loading && "opacity-50",
        )}
      >
        {loading ? "…" : hasData ? count : t.todoCounts.unavailable}
      </span>
    </span>
  );
}
