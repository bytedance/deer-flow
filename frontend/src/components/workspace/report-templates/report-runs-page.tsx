"use client";

import Link from "next/link";

import { useReportRuns } from "@/core/report-templates";
import type { RunStatus } from "@/core/report-templates/types";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<RunStatus, string> = {
  pending: "等待中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
  canceled: "已取消",
};

const STATUS_COLOR: Record<RunStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  succeeded: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  failed: "bg-red-500/15 text-red-700 dark:text-red-300",
  canceled: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};

export function ReportRunsPage() {
  const { runs, isLoading, error } = useReportRuns({ limit: 100 });

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header>
        <h1 className="text-2xl font-semibold">报告历史</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          已生成的报告会按时间排序展示在此。点击查看 payload、artifact 下载链接。
        </p>
      </header>

      {isLoading && (
        <div className="text-muted-foreground text-sm">加载中…</div>
      )}
      {error && (
        <div className="rounded border border-destructive bg-destructive/10 p-3 text-sm">
          加载失败：{String(error)}
        </div>
      )}
      {!isLoading && !error && runs.length === 0 && (
        <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
          暂无报告运行记录。先在子智能体或自定义模板中跑一次报告。
        </div>
      )}

      {!isLoading && !error && runs.length > 0 && (
        <div className="overflow-x-auto rounded border bg-card">
          <table className="min-w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">运行 ID</th>
                <th className="px-3 py-2 text-left font-medium">模板</th>
                <th className="px-3 py-2 text-left font-medium">状态</th>
                <th className="px-3 py-2 text-left font-medium">创建时间</th>
                <th className="px-3 py-2 text-left font-medium">参数摘要</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.id}
                  className="border-t transition-colors hover:bg-accent"
                >
                  <td className="px-3 py-2">
                    <Link
                      href={`/workspace/report-runs/${run.id}`}
                      className="font-mono text-xs text-foreground underline-offset-2 hover:underline"
                    >
                      {run.id.slice(0, 12)}…
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/workspace/report-templates/${run.template_id}`}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      {run.template_version_ref ?? `v${run.template_version}`}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-xs",
                        STATUS_COLOR[run.status],
                      )}
                    >
                      {STATUS_LABEL[run.status] ?? run.status}
                    </span>
                    {run.error_code && (
                      <div className="text-muted-foreground mt-0.5 text-xs">
                        {run.error_code}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {new Date(run.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    <div className="text-muted-foreground line-clamp-1 max-w-[24rem] text-xs">
                      {Object.entries(run.parameters_summary)
                        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                        .join("  ")}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
