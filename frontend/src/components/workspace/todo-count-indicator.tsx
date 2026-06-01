"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bell, Play, Power } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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

interface TodoItem {
  key: string;
  icon: React.ReactNode;
  label: string;
  count: number;
  color: string;
}

// ---------------------------------------------------------------------------
// Indicator
// ---------------------------------------------------------------------------

export function TodoCountIndicator() {
  const { t } = useI18n();
  const [counts, setCounts] = useState<TodoCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetch = useCallback(async () => {
    try {
      const res = await fetchGateway(
        `${getBackendBaseURL()}/api/workbench/todo-stats`,
      );
      if (res.ok) {
        const data = (await res.json()) as TodoCounts;
        setCounts(data);
        setLastUpdated(new Date());
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

  const total = useMemo(() => {
    if (!counts) return 0;
    return counts.anomalyPending + counts.startupPending + counts.shutdownPending;
  }, [counts]);

  const items: TodoItem[] = useMemo(() => {
    const c = counts;
    return [
      {
        key: "anomaly",
        icon: <AlertTriangle className="size-4" />,
        label: t.todoCounts.anomalyPending,
        count: c?.anomalyPending ?? 0,
        color: "text-amber-600 bg-amber-100 dark:text-amber-400 dark:bg-amber-950",
      },
      {
        key: "startup",
        icon: <Play className="size-4" />,
        label: t.todoCounts.startupPending,
        count: c?.startupPending ?? 0,
        color: "text-blue-600 bg-blue-100 dark:text-blue-400 dark:bg-blue-950",
      },
      {
        key: "shutdown",
        icon: <Power className="size-4" />,
        label: t.todoCounts.shutdownPending,
        count: c?.shutdownPending ?? 0,
        color: "text-gray-600 bg-gray-100 dark:text-gray-400 dark:bg-gray-800",
      },
    ];
  }, [counts, t]);

  const hasPending = total > 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn(
            "relative size-8",
            hasPending && "text-amber-600 dark:text-amber-400",
          )}
        >
          <Bell className={cn("size-4", loading && "animate-pulse")} />
          {hasPending && (
            <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-white">
              {total > 99 ? "99+" : total}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          {t.todoCounts.loading}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.map((item) => (
          <div
            key={item.key}
            className="flex items-center gap-3 px-2 py-2 text-sm cursor-default"
          >
            <span
              className={cn(
                "flex size-6 items-center justify-center rounded",
                item.color,
              )}
            >
              {item.icon}
            </span>
            <span className="flex-1">{item.label}</span>
            <span className="tabular-nums font-semibold">{item.count}</span>
          </div>
        ))}
        {lastUpdated && (
          <>
            <DropdownMenuSeparator />
            <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
              {lastUpdated.toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </div>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
