"use client";

import Link from "next/link";

import { useReportRun, useReportRunPayload } from "@/core/report-templates";

interface Props {
  runId: string;
}

function _artifactUrl(threadId: string, path: string): string {
  // Path is absolute on the host; we strip everything before `/mnt/user-data/`
  // and let the Gateway artifact router resolve it via the virtual path.
  const idx = path.indexOf("user-data/");
  if (idx < 0) return path;
  const virtualSuffix = path.slice(idx);
  return `/api/threads/${threadId}/artifacts/mnt/${virtualSuffix}`;
}

export function ReportRunDetailPage({ runId }: Props) {
  const { run, isLoading, error } = useReportRun(runId);
  const { payload } = useReportRunPayload(runId);

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">加载中…</div>;
  }
  if (error || !run) {
    return (
      <div className="p-6">
        <Link href="/workspace/report-runs" className="text-sm underline">
          ← 返回历史
        </Link>
        <div className="mt-4 rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {error ? String(error) : "运行记录不存在"}
        </div>
      </div>
    );
  }

  const md = run.artifact_paths?.md;
  const pdf = run.artifact_paths?.pdf;

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/workspace/report-runs"
            className="text-muted-foreground text-xs underline-offset-2 hover:underline"
          >
            ← 报告历史
          </Link>
          <h1 className="mt-1 font-mono text-lg font-semibold">{run.id}</h1>
          <div className="text-muted-foreground mt-1 text-xs">
            模板{" "}
            <Link
              className="underline-offset-2 hover:underline"
              href={`/workspace/report-templates/${run.template_id}`}
            >
              {run.template_version_ref ?? `v${run.template_version}`}
            </Link>{" "}
            · 状态 <span className="font-medium">{run.status}</span> · 创建{" "}
            {new Date(run.created_at).toLocaleString()}
          </div>
        </div>
        <div className="flex gap-2">
          {md && (
            <a
              className="rounded border px-3 py-1.5 text-sm hover:bg-accent"
              href={_artifactUrl(run.thread_id, md)}
              target="_blank"
              rel="noreferrer"
            >
              下载 Markdown
            </a>
          )}
          {pdf ? (
            <a
              className="rounded border px-3 py-1.5 text-sm hover:bg-accent"
              href={_artifactUrl(run.thread_id, pdf)}
              target="_blank"
              rel="noreferrer"
            >
              下载 PDF
            </a>
          ) : run.pdf_skipped_reason ? (
            <span className="rounded border px-3 py-1.5 text-sm text-muted-foreground">
              PDF 不可用（{run.pdf_skipped_reason}）
            </span>
          ) : null}
        </div>
      </header>

      {run.error_message && (
        <div className="rounded border border-destructive bg-destructive/10 p-3 text-sm">
          <div className="font-medium">运行失败：{run.error_code}</div>
          <div className="mt-1 text-xs">{run.error_message}</div>
        </div>
      )}

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">参数摘要</h2>
        <pre className="overflow-x-auto text-xs">
          {JSON.stringify(run.parameters_summary, null, 2)}
        </pre>
      </section>

      <section className="flex-1 overflow-hidden rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">报告 Payload</h2>
        {payload ? (
          <pre className="h-full overflow-auto text-xs">
            {JSON.stringify(payload, null, 2)}
          </pre>
        ) : (
          <div className="text-muted-foreground text-xs">
            {run.report_payload_path
              ? "payload 加载中…"
              : "尚未生成 payload。"}
          </div>
        )}
      </section>
    </div>
  );
}
