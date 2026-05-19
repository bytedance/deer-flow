"use client";

import { useState } from "react";

import { useClosureRefresh, useClosureSummary } from "@/core/closed-loop";

import { ClosureDetailDrawer } from "./closure-detail-drawer";
import { ClosureKanban } from "./closure-kanban";
import { ClosureList } from "./closure-list";
import { CreateClosureTicketDialog } from "./create-closure-ticket-dialog";

type ViewMode = "list" | "kanban";

export function ClosedLoopPage() {
  const [view, setView] = useState<ViewMode>("list");
  const [activeTicketId, setActiveTicketId] = useState<string | null>(null);
  const { summary } = useClosureSummary({ refetchInterval: 60_000 });

  // Background refresh via polling + closure event bus.
  useClosureRefresh();

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">闭环管理</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            统一登记 / 派单 / 处置 / 验证关闭设备整改单。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {summary && (
            <div className="flex gap-2">
              <Pill label="未关闭" value={summary.open} tone="info" />
              <Pill
                label="超期"
                value={summary.overdue}
                tone={summary.overdue > 0 ? "danger" : "muted"}
              />
              <Pill
                label="待验证"
                value={summary.pending_verification}
                tone="warning"
              />
              <Pill
                label="待我处理"
                value={summary.assigned_to_me}
                tone={summary.assigned_to_me > 0 ? "info" : "muted"}
              />
            </div>
          )}
          <ViewToggle view={view} onChange={setView} />
          <CreateClosureTicketDialog onCreated={setActiveTicketId} />
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {view === "list" ? (
          <ClosureList onSelect={setActiveTicketId} />
        ) : (
          <ClosureKanban onSelect={setActiveTicketId} />
        )}
      </div>

      <ClosureDetailDrawer
        ticketId={activeTicketId}
        onClose={() => setActiveTicketId(null)}
      />
    </div>
  );
}

function Pill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "info" | "warning" | "danger" | "muted";
}) {
  const cls =
    tone === "danger"
      ? "bg-red-500/15 text-red-700 dark:text-red-300"
      : tone === "warning"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
        : tone === "info"
          ? "bg-blue-500/15 text-blue-700 dark:text-blue-300"
          : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-full px-3 py-1 ${cls}`}>
      {label}: <span className="font-semibold">{value}</span>
    </span>
  );
}

function ViewToggle({
  view,
  onChange,
}: {
  view: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  return (
    <div className="bg-muted text-muted-foreground inline-flex rounded-md text-xs">
      {(["list", "kanban"] as const).map((mode) => (
        <button
          key={mode}
          type="button"
          className={`rounded-md px-3 py-1 transition-colors ${
            view === mode
              ? "bg-background text-foreground shadow-sm"
              : "hover:text-foreground"
          }`}
          onClick={() => onChange(mode)}
        >
          {mode === "list" ? "列表" : "看板"}
        </button>
      ))}
    </div>
  );
}
