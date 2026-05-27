"use client";

import { useState } from "react";

import {
  useClosureTicket,
  useClosureTicketEvents,
  useTransitionClosureTicket,
} from "@/core/closed-loop";
import type {
  ClosureAction,
  ClosureStatus,
  ClosureTicket,
} from "@/core/closed-loop";

import { ClosureActionForm } from "./closure-action-form";

const STATUS_LABEL: Record<ClosureStatus, string> = {
  pending: "待派单",
  assigned: "已派单",
  in_progress: "处置中",
  pending_verification: "待验证",
  closed: "已关闭",
  rejected: "已退回",
};

export interface ClosureDetailDrawerProps {
  ticketId: string | null;
  onClose: () => void;
}

export function ClosureDetailDrawer({
  ticketId,
  onClose,
}: ClosureDetailDrawerProps) {
  const { ticket, isLoading } = useClosureTicket(ticketId);
  const { events } = useClosureTicketEvents(ticketId);
  const transition = useTransitionClosureTicket();
  const [actionError, setActionError] = useState<string | null>(null);

  const open = Boolean(ticketId);

  if (!open) return null;

  const performAction = async (
    action: ClosureAction,
    payload?: Record<string, unknown>,
  ) => {
    if (!ticketId) return;
    setActionError(null);
    try {
      await transition.mutateAsync({
        ticketId,
        request: { action, payload },
      });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={onClose}
        role="presentation"
      />
      <aside
        role="dialog"
        aria-label="闭环单详情"
        className="bg-background fixed right-0 top-0 z-50 h-full w-full max-w-[480px] overflow-y-auto border-l shadow-lg"
      >
        <header className="bg-background sticky top-0 z-10 flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-base font-semibold">闭环单详情</h2>
          <button
            type="button"
            className="hover:bg-accent rounded px-2 py-1 text-sm"
            onClick={onClose}
            aria-label="关闭"
          >
            ✕
          </button>
        </header>

        <div className="space-y-5 p-4 text-sm">
          {isLoading && (
            <div className="text-muted-foreground">加载中…</div>
          )}
          {!isLoading && !ticket && (
            <div className="text-muted-foreground">未找到该工单。</div>
          )}
          {ticket && (
            <>
              <TicketSummary ticket={ticket} />

              {ticket.source_run_id && (
                <SourceLink ticket={ticket} />
              )}

              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  可执行动作
                </h3>
                {actionError && (
                  <div className="mb-2 rounded border border-destructive/50 bg-destructive/10 p-2 text-xs">
                    {actionError}
                  </div>
                )}
                <ClosureActionForm
                  ticket={ticket}
                  pending={transition.isPending}
                  onSubmit={performAction}
                />
              </section>

              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  时间线
                </h3>
                <ol className="space-y-1.5 text-xs">
                  {events.length === 0 && (
                    <li className="text-muted-foreground">暂无事件。</li>
                  )}
                  {[...events]
                    .sort(
                      (a, b) =>
                        new Date(b.created_at).getTime() -
                        new Date(a.created_at).getTime(),
                    )
                    .map((e) => {
                      const ts = e.created_at ? new Date(e.created_at) : null;
                      const tsValid = ts !== null && !Number.isNaN(ts.getTime());
                      return (
                      <li
                        key={e.id}
                        className="bg-muted/30 rounded border p-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{e.action}</span>
                          <span className="text-muted-foreground">
                            {tsValid
                              ? ts.toLocaleString("zh-CN")
                              : "—"}
                          </span>
                        </div>
                        <div className="text-muted-foreground mt-0.5">
                          {e.from_status ?? "—"} → {e.to_status ?? "—"}{" "}
                          {e.actor_id && `· ${e.actor_id}`}
                        </div>
                        {!!e.payload?.verification_summary && (
                          <div className="mt-1.5 rounded bg-emerald-500/10 px-2 py-1 text-[11px]">
                            <span className="font-medium text-emerald-700 dark:text-emerald-300">验证摘要：</span>
                            <span className="text-muted-foreground whitespace-pre-wrap">
                              {String(e.payload.verification_summary)}
                            </span>
                          </div>
                        )}
                        {!!e.payload?.rejection_reason && (
                          <div className="mt-1.5 rounded bg-red-500/10 px-2 py-1 text-[11px]">
                            <span className="font-medium text-red-700 dark:text-red-300">退回原因：</span>
                            <span className="text-muted-foreground whitespace-pre-wrap">
                              {String(e.payload.rejection_reason)}
                            </span>
                          </div>
                        )}
                        {!!e.payload?.assignee_id && e.action === "assign" && (
                          <div className="text-muted-foreground mt-0.5 text-[11px]">
                            派单给：{String(e.payload.assignee_id)}
                          </div>
                        )}
                      </li>
                      );
                    })}
                </ol>
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function TicketSummary({ ticket }: { ticket: ClosureTicket }) {
  return (
    <section className="space-y-2">
      <div>
        <div className="font-mono text-xs text-muted-foreground">
          {ticket.id}
        </div>
        <h3 className="mt-1 text-base font-semibold">{ticket.title}</h3>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-xs">
        <Row k="状态" v={STATUS_LABEL[ticket.status]} />
        <Row k="优先级" v={ticket.priority} />
        <Row k="设备" v={ticket.device_name ?? ticket.device_id ?? "—"} />
        <Row k="受理人" v={ticket.assignee_id ?? "—"} />
        <Row k="来源" v={ticket.source_type} />
        <Row
          k="SLA"
          v={
            ticket.due_at
              ? new Date(ticket.due_at).toLocaleString("zh-CN") +
                (ticket.is_overdue ? "（超期）" : "")
              : "—"
          }
          tone={ticket.is_overdue ? "danger" : undefined}
        />
        <Row k="创建" v={new Date(ticket.created_at).toLocaleString("zh-CN")} />
        <Row
          k="关闭"
          v={
            ticket.closed_at
              ? new Date(ticket.closed_at).toLocaleString("zh-CN")
              : "—"
          }
        />
      </dl>
      {ticket.description && (
        <p className="text-muted-foreground whitespace-pre-wrap text-xs">
          {ticket.description}
        </p>
      )}
    </section>
  );
}

function Row({
  k,
  v,
  tone,
}: {
  k: string;
  v: string;
  tone?: "danger";
}) {
  return (
    <div>
      <dt className="text-muted-foreground">{k}</dt>
      <dd
        className={tone === "danger" ? "text-red-600 dark:text-red-400" : ""}
      >
        {v}
      </dd>
    </div>
  );
}

function SourceLink({ ticket }: { ticket: ClosureTicket }) {
  let href: string | null = null;
  let label = "";

  if (ticket.source_type === "report" && ticket.source_run_id) {
    href = `/workspace/report-runs/${ticket.source_run_id}`;
    label = "前往报告详情";
  } else if (ticket.source_type === "diagnosis" && ticket.source_thread_id) {
    href = `/workspace/chats/${ticket.source_thread_id}`;
    label = "前往诊断会话";
  } else if (ticket.source_thread_id) {
    href = `/workspace/chats/${ticket.source_thread_id}`;
    label = "前往来源会话";
  }

  if (!href) return null;
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        来源
      </h3>
      <a
        href={href}
        className="text-xs underline-offset-2 hover:underline"
      >
        {label} →
      </a>
    </section>
  );
}
