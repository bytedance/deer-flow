"use client";

import Link from "next/link";

import { useClosureTickets } from "@/core/closed-loop";
import type { ClosureStatus, ClosureTicket } from "@/core/closed-loop";

const STATUS_LABEL: Record<ClosureStatus, string> = {
  pending: "待派单",
  assigned: "已派单",
  in_progress: "处置中",
  pending_verification: "待验证",
  closed: "已关闭",
  rejected: "已退回",
};

const STATUS_COLOR: Record<ClosureStatus, string> = {
  pending: "bg-amber-100 text-amber-800",
  assigned: "bg-blue-100 text-blue-800",
  in_progress: "bg-indigo-100 text-indigo-800",
  pending_verification: "bg-purple-100 text-purple-800",
  closed: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
};

export function LinkedClosureTickets({ sourceRunId }: { sourceRunId: string }) {
  const { tickets, isLoading, error } = useClosureTickets({
    source_run_id: sourceRunId,
    page_size: 20,
    order_by: "created_at",
    order_desc: true,
  });

  if (isLoading) {
    return <p className="text-muted-foreground text-xs">加载中...</p>;
  }

  if (error) {
    return <p className="text-xs text-destructive">加载失败: {String(error)}</p>;
  }

  const linked = tickets ?? [];

  if (linked.length === 0) {
    return <p className="text-muted-foreground text-xs">暂无关联整改单。</p>;
  }

  return (
    <ul className="space-y-1.5">
      {linked.map((ticket) => (
        <li key={ticket.id} className="text-xs">
          <LinkedTicketItem ticket={ticket} />
        </li>
      ))}
    </ul>
  );
}

function LinkedTicketItem({ ticket }: { ticket: ClosureTicket }) {
  return (
    <div className="flex items-center gap-2 rounded border bg-muted/30 px-3 py-1.5">
      <Link
        href={`/workspace/closed-loop?ticket=${ticket.id}`}
        className="text-primary hover:underline font-medium flex-1 truncate"
      >
        {ticket.title}
      </Link>
      <span
        className={`inline-block px-1.5 py-0.5 text-[10px] rounded ${STATUS_COLOR[ticket.status]}`}
      >
        {STATUS_LABEL[ticket.status]}
      </span>
      <span className="text-muted-foreground text-[10px]">
        {ticket.priority}
      </span>
    </div>
  );
}
