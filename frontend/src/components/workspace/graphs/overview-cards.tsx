"use client";

import { TrendingUpIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import type { MetricCard } from "./types";

export function OverviewCards({ cards }: { cards: MetricCard[] }) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.id}
          className="rounded-xl border bg-card p-4 shadow-sm transition-shadow hover:shadow-md"
        >
          <p className="text-muted-foreground text-xs font-medium">{card.label}</p>
          <p className="mt-1 text-2xl font-bold tracking-tight">{card.value}</p>
          {card.change && (
            <div className="mt-1 flex items-center gap-1">
              <TrendingUpIcon
                className={cn(
                  "size-3",
                  card.change.startsWith("+")
                    ? "text-emerald-500"
                    : card.change.startsWith("-")
                      ? "rotate-180 text-red-500"
                      : "text-muted-foreground",
                )}
              />
              <span
                className={cn(
                  "text-xs font-medium",
                  card.change.startsWith("+")
                    ? "text-emerald-500"
                    : card.change.startsWith("-")
                      ? "text-red-500"
                      : "text-muted-foreground",
                )}
              >
                {card.change}
              </span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
