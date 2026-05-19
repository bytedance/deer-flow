"use client";

import { useMemo } from "react";

import { useClosureTickets } from "@/core/closed-loop";
import type { ClosureStatus, ClosureTicket } from "@/core/closed-loop";

const COLUMNS: { status: ClosureStatus; label: string; tone: string }[] = [
  { status: "pending", label: "待派单", tone: "border-zinc-400" },
  { status: "assigned", label: "已派单", tone: "border-blue-400" },
  { status: "in_progress", label: "处置中", tone: "border-amber-400" },
  {
    status: "pending_verification",
    label: "待验证",
    tone: "border-purple-400",
  },
  { status: "closed", label: "已关闭", tone: "border-emerald-500" },
];

export interface ClosureKanbanProps {
  onSelect: (ticketId: string) => void;
}

export function ClosureKanban({ onSelect }: ClosureKanbanProps) {
  const { tickets, isLoading, error } = useClosureTickets({
    page_size: 200,
    order_by: "created_at",
    order_desc: true,
  });

  const grouped = useMemo(() => {
    const map = new Map<ClosureStatus, ClosureTicket[]>();
    for (const c of COLUMNS) map.set(c.status, []);
    for (const t of tickets) {
      const list = map.get(t.status);
      if (list) list.push(t);
    }
    return map;
  }, [tickets]);

  if (isLoading) {
    return <div className="text-muted-foreground text-sm">加载中…</div>;
  }
  if (error) {
    return (
      <div className="border-destructive bg-destructive/10 rounded border p-3 text-sm">
        加载失败：{String(error)}
      </div>
    );
  }

  return (
    <div className="grid h-full grid-cols-1 gap-3 overflow-x-auto md:grid-cols-3 lg:grid-cols-5">
      {COLUMNS.map((col) => {
        const items = grouped.get(col.status) ?? [];
        return (
          <div
            key={col.status}
            className={`bg-muted/20 flex min-h-0 flex-col rounded border-t-2 ${col.tone}`}
          >
            <div className="flex items-center justify-between border-b px-3 py-2 text-xs">
              <span className="font-medium">{col.label}</span>
              <span className="text-muted-foreground">{items.length}</span>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
              {items.length === 0 && (
                <div className="text-muted-foreground/60 text-center text-xs">
                  无
                </div>
              )}
              {items.map((t) => (
                <button
                  type="button"
                  key={t.id}
                  className={
                    "bg-card hover:border-foreground/30 w-full rounded border p-2 text-left text-xs transition-colors " +
                    (t.is_overdue ? "border-red-400" : "")
                  }
                  onClick={() => onSelect(t.id)}
                >
                  <div className="line-clamp-2 font-medium">{t.title}</div>
                  <div className="text-muted-foreground mt-1 flex items-center justify-between text-[11px]">
                    <span>{t.device_name ?? t.device_id ?? "—"}</span>
                    <span>{t.priority}</span>
                  </div>
                  {t.is_overdue && t.due_at && (
                    <div className="mt-1 text-[11px] text-red-600 dark:text-red-400">
                      超期 · {new Date(t.due_at).toLocaleString("zh-CN")}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
