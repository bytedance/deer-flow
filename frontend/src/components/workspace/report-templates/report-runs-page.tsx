"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import { useReportRuns, useReportThreads } from "@/core/report-templates";
import type { RunStatus } from "@/core/report-templates/types";
import { buildCrossPageURL, logCrossPageNavigation } from "@/core/models/navigation";
import { titleOfThread, pathOfThread } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

import { ThreadActionMenu } from "./thread-action-menu";

const STATUS_COLOR: Record<RunStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  success: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  failed: "bg-red-500/15 text-red-700 dark:text-red-300",
  cancelled: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};

function RunsTab() {
  const { t } = useI18n();
  const { runs, isLoading, error } = useReportRuns({ limit: 100 });

  const STATUS_LABEL: Record<RunStatus, string> = {
    pending: t.reportRuns.statusPending,
    running: t.reportRuns.statusRunning,
    success: t.reportRuns.statusSuccess,
    failed: t.reportRuns.statusFailed,
    cancelled: t.reportRuns.statusCancelled,
  };

  if (isLoading) {
    return <div className="text-muted-foreground text-sm">{t.reportRuns.loading}</div>;
  }
  if (error) {
    return (
      <div className="rounded border border-destructive bg-destructive/10 p-3 text-sm">
        {t.reportRuns.loadingFailed}：{String(error)}
      </div>
    );
  }
  if (runs.length === 0) {
    return (
      <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
        {t.reportRuns.emptyRuns}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded border bg-card">
      <table className="min-w-full text-sm">
        <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">{t.reportRuns.headerRunId}</th>
            <th className="px-3 py-2 text-left font-medium">{t.reportRuns.headerTemplate}</th>
            <th className="px-3 py-2 text-left font-medium">{t.reportRuns.headerVersion}</th>
            <th className="px-3 py-2 text-left font-medium">{t.reportRuns.headerStatus}</th>
            <th className="px-3 py-2 text-left font-medium">{t.reportRuns.headerCreatedAt}</th>
            <th className="px-3 py-2 text-left font-medium">{t.reportRuns.headerParams}</th>
            <th className="px-3 py-2 text-left font-medium">{t.reportRuns.headerSourceChat}</th>
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
              <td className="px-3 py-2 text-xs text-muted-foreground">
                {run.template_version != null
                  ? `v${run.template_version}`
                  : run.template_version_ref ?? "—"}
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
              <td className="px-3 py-2">
                {run.thread_id ? (
                  <Link
                    href={buildCrossPageURL(pathOfThread(run.thread_id), {
                      sourceType: "report",
                      sourceId: run.id,
                      threadId: run.thread_id,
                      runId: run.run_id,
                    })}
                    onClick={() =>
                      logCrossPageNavigation(
                        {
                          sourceType: "report",
                          sourceId: run.id,
                          threadId: run.thread_id,
                          runId: run.run_id,
                        },
                        "outbound",
                      )
                    }
                    className="font-mono text-xs text-muted-foreground underline-offset-2 hover:underline"
                  >
                    {run.thread_id.slice(0, 12)}…
                  </Link>
                ) : (
                  <span className="text-muted-foreground text-xs">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChatsTab() {
  const { t } = useI18n();
  const { threads, isLoading, error } = useReportThreads();

  if (isLoading) {
    return <div className="text-muted-foreground text-sm">{t.reportRuns.loading}</div>;
  }
  if (error) {
    return (
      <div className="rounded border border-destructive bg-destructive/10 p-3 text-sm">
        {t.reportRuns.loadingFailed}：{String(error)}
      </div>
    );
  }
  if (threads.length === 0) {
    return (
      <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
        {t.reportRuns.emptyChats}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {threads.map((thread) => (
        <div
          key={thread.thread_id}
          className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-accent group"
        >
          <Link
            href={pathOfThread(thread)}
            className="flex-1 flex items-center gap-3 min-w-0"
          >
            <span className="text-foreground truncate">
              {titleOfThread(thread)}
            </span>
            <span className="text-muted-foreground shrink-0 text-xs">
              {thread.updated_at
                ? new Date(thread.updated_at).toLocaleDateString()
                : ""}
            </span>
          </Link>
          <ThreadActionMenu thread={thread} sidebarStyle={false} />
        </div>
      ))}
    </div>
  );
}

export function ReportRunsPage() {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") === "chats" ? "chats" : "runs";

  const handleTabChange = useCallback(
    (value: string) => {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", value);
      window.history.replaceState({}, "", url.toString());
    },
    [],
  );

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header>
        <h1 className="text-2xl font-semibold">{t.reportRuns.pageTitle}</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          {t.reportRuns.pageDescription}
        </p>
      </header>

      <Tabs value={tab} onValueChange={handleTabChange}>
        <TabsList>
          <TabsTrigger value="runs">{t.reportRuns.tabRuns}</TabsTrigger>
          <TabsTrigger value="chats">{t.reportRuns.tabChats}</TabsTrigger>
        </TabsList>
        <TabsContent value="runs" className="mt-4">
          <RunsTab />
        </TabsContent>
        <TabsContent value="chats" className="mt-4">
          <ChatsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
