"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { useClosureTickets } from "@/core/closed-loop";
import type {
  ClosurePriority,
  ClosureSourceType,
  ClosureStatus,
  ListClosureTicketsParams,
} from "@/core/closed-loop";

const STATUS_LABEL: Record<ClosureStatus, string> = {
  pending: "待派单",
  assigned: "已派单",
  in_progress: "处置中",
  pending_verification: "待验证",
  closed: "已关闭",
  rejected: "已退回",
};

const STATUS_TONE: Record<ClosureStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  assigned: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  in_progress: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  pending_verification: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  closed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  rejected: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300",
};

const PRIORITY_LABEL: Record<ClosurePriority, string> = {
  urgent: "紧急",
  important: "重要",
  normal: "一般",
  observe: "观察",
};

const SOURCE_LABEL: Record<ClosureSourceType, string> = {
  diagnosis: "诊断",
  daily_report: "日报",
  weekly_report: "周报",
  monthly_report: "月报",
  custom_report: "自定义",
  manual: "手工",
};

export interface ClosureListProps {
  onSelect: (ticketId: string) => void;
}

export function ClosureList({ onSelect }: ClosureListProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useMemo<ListClosureTicketsParams>(() => {
    const status = searchParams.get("status");
    const priority = searchParams.get("priority");
    const source = searchParams.get("source");
    const isOverdue = searchParams.get("overdue");
    const page = Number(searchParams.get("page") ?? "1");
    return {
      status: status ? (status as ClosureStatus) : undefined,
      priority: priority ? (priority as ClosurePriority) : undefined,
      source_type: source ? (source as ClosureSourceType) : undefined,
      is_overdue: isOverdue === "true" ? true : undefined,
      page,
      page_size: 50,
      order_by: "created_at",
      order_desc: true,
    };
  }, [searchParams]);

  const updateQuery = (
    next: Partial<Record<"status" | "priority" | "source" | "overdue" | "page", string | undefined>>,
  ) => {
    const usp = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(next)) {
      if (v === undefined || v === "") {
        usp.delete(k);
      } else {
        usp.set(k, v);
      }
    }
    router.replace(`?${usp.toString()}`);
  };

  const { tickets, meta, isLoading, error } = useClosureTickets(params);

  return (
    <div className="flex h-full flex-col gap-3">
      <FilterBar
        params={params}
        onChange={(patch) =>
          updateQuery({
            status: patch.status ?? "",
            priority: patch.priority ?? "",
            source: patch.source_type ?? "",
            overdue: patch.is_overdue ? "true" : "",
            page: "1",
          })
        }
      />

      {isLoading && <div className="text-muted-foreground text-sm">加载中…</div>}
      {error && (
        <div className="border-destructive bg-destructive/10 rounded border p-3 text-sm">
          加载失败：{String(error)}
        </div>
      )}

      {!isLoading && !error && tickets.length === 0 && (
        <div className="text-muted-foreground rounded border border-dashed p-8 text-center text-sm">
          没有符合条件的闭环单。
        </div>
      )}

      {!isLoading && !error && tickets.length > 0 && (
        <>
          <div className="bg-card overflow-x-auto rounded border">
            <table className="min-w-full text-sm">
              <thead className="bg-muted/50 text-muted-foreground text-xs uppercase">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">单号</th>
                  <th className="px-3 py-2 text-left font-medium">标题</th>
                  <th className="px-3 py-2 text-left font-medium">设备</th>
                  <th className="px-3 py-2 text-left font-medium">状态</th>
                  <th className="px-3 py-2 text-left font-medium">优先级</th>
                  <th className="px-3 py-2 text-left font-medium">来源</th>
                  <th className="px-3 py-2 text-left font-medium">受理人</th>
                  <th className="px-3 py-2 text-left font-medium">SLA</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => (
                  <tr
                    key={t.id}
                    className={
                      "hover:bg-accent cursor-pointer border-t transition-colors " +
                      (t.is_overdue ? "bg-red-500/5" : "")
                    }
                    onClick={() => onSelect(t.id)}
                  >
                    <td className="px-3 py-2 font-mono text-xs">
                      {t.id.slice(0, 12)}…
                    </td>
                    <td className="px-3 py-2">{t.title}</td>
                    <td className="px-3 py-2 text-xs">
                      {t.device_name ?? t.device_id ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${STATUS_TONE[t.status]}`}
                      >
                        {STATUS_LABEL[t.status]}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {PRIORITY_LABEL[t.priority]}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {SOURCE_LABEL[t.source_type]}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {t.assignee_id ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {t.due_at ? (
                        <span
                          className={
                            t.is_overdue ? "text-red-600 dark:text-red-400" : ""
                          }
                          title={t.due_at}
                        >
                          {new Date(t.due_at).toLocaleString("zh-CN")}
                          {t.is_overdue && " · 超期"}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {meta && meta.total > meta.page_size && (
            <div className="text-muted-foreground flex items-center justify-between text-xs">
              <span>
                共 {meta.total} 条 · 第 {meta.page} 页
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="hover:bg-accent rounded border px-2 py-1 disabled:opacity-50"
                  disabled={meta.page <= 1}
                  onClick={() =>
                    updateQuery({ page: String(Math.max(1, meta.page - 1)) })
                  }
                >
                  上一页
                </button>
                <button
                  type="button"
                  className="hover:bg-accent rounded border px-2 py-1 disabled:opacity-50"
                  disabled={meta.page * meta.page_size >= meta.total}
                  onClick={() => updateQuery({ page: String(meta.page + 1) })}
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function FilterBar({
  params,
  onChange,
}: {
  params: ListClosureTicketsParams;
  onChange: (next: ListClosureTicketsParams) => void;
}) {
  return (
    <div className="bg-muted/30 flex flex-wrap items-center gap-2 rounded border p-2 text-xs">
      <Selector
        label="状态"
        value={params.status ?? ""}
        options={[
          { value: "", label: "全部" },
          ...Object.entries(STATUS_LABEL).map(([v, label]) => ({
            value: v,
            label,
          })),
        ]}
        onChange={(v) => onChange({ ...params, status: (v || undefined) as ClosureStatus })}
      />
      <Selector
        label="优先级"
        value={params.priority ?? ""}
        options={[
          { value: "", label: "全部" },
          ...Object.entries(PRIORITY_LABEL).map(([v, label]) => ({
            value: v,
            label,
          })),
        ]}
        onChange={(v) => onChange({ ...params, priority: (v || undefined) as ClosurePriority })}
      />
      <Selector
        label="来源"
        value={params.source_type ?? ""}
        options={[
          { value: "", label: "全部" },
          ...Object.entries(SOURCE_LABEL).map(([v, label]) => ({
            value: v,
            label,
          })),
        ]}
        onChange={(v) => onChange({ ...params, source_type: (v || undefined) as ClosureSourceType })}
      />
      <label className="ml-auto flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={Boolean(params.is_overdue)}
          onChange={(e) =>
            onChange({ ...params, is_overdue: e.target.checked || undefined })
          }
        />
        仅看超期
      </label>
    </div>
  );
}

function Selector({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (next: string) => void;
}) {
  return (
    <label className="flex items-center gap-1">
      <span className="text-muted-foreground">{label}:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-background rounded border px-1.5 py-0.5 text-xs"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
