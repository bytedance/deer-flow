"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";
import { Store } from "lucide-react";

import { GenUIRenderer } from "@/components/genui/GenUIRenderer";
import { useI18n } from "@/core/i18n/hooks";
import type { DataFileEntry, ReportRun } from "@/core/report-templates";
import type { UIBlock } from "@/core/genui/store";
import {
  decodeCrossPageContext,
  logCrossPageNavigation,
} from "@/core/models/navigation";
import { useReportRun, useReportRunPayload, useReportTemplate } from "@/core/report-templates";
import { pathOfThread } from "@/core/threads/utils";

import { SourceBreadcrumb } from "../source-breadcrumb";
import { CreateClosureTicketDialog } from "../closed-loop/create-closure-ticket-dialog";
import { LinkedClosureTickets } from "../closed-loop/linked-closure-tickets";
import type { CreateTicketSourceContext } from "../closed-loop/create-closure-ticket-dialog";

interface Props {
  runId: string;
}

type PayloadSection = {
  id?: string | number;
  title?: string;
  component?: string;
  props?: Record<string, unknown>;
};

function artifactUrl(threadId: string, path: string): string {
  const idx = path.indexOf("user-data/");
  if (idx < 0) return path;
  const virtualSuffix = path.slice(idx);
  return `/api/threads/${threadId}/artifacts/mnt/${virtualSuffix}`;
}

function dataFileArtifactUrl(threadId: string, dataFilePath: string): string {
  const idx = dataFilePath.indexOf("user-data/");
  if (idx >= 0) {
    return `/api/threads/${threadId}/artifacts/mnt/${dataFilePath.slice(idx)}`;
  }
  return `/api/threads/${threadId}/artifacts?path=${encodeURIComponent(dataFilePath)}`;
}

type ErrorSeverity = "destructive" | "warning";

function getErrorSeverity(errorCode: string | null | undefined): ErrorSeverity {
  if (!errorCode) return "destructive";
  if (errorCode.startsWith("TEMPLATE_UNAVAILABLE")) return "warning";
  return "destructive";
}

function getErrorLabel(errorCode: string | null | undefined): string {
  if (!errorCode) return "Run failed";
  if (errorCode.startsWith("TEMPLATE_UNAVAILABLE")) return "Template unavailable";
  if (errorCode.startsWith("KB_UNAVAILABLE")) return "Knowledge source unavailable";
  if (errorCode.startsWith("RUN_INTERRUPTED")) return "Run interrupted";
  if (errorCode.startsWith("DATA_STEP_FAILED")) return "Data step failed";
  return errorCode;
}

function buildPayloadBlocks(
  runId: string,
  payload: Record<string, unknown> | undefined,
): UIBlock[] {
  const sections = payload?.sections;
  if (!Array.isArray(sections)) {
    return [];
  }

  return sections.flatMap((rawSection, index) => {
    if (typeof rawSection !== "object" || rawSection === null) {
      return [];
    }

    const section = rawSection as PayloadSection;
    if (!section.component || typeof section.component !== "string") {
      return [];
    }

    const props =
      section.props && typeof section.props === "object"
        ? { ...section.props }
        : {};
    if (section.title && !("title" in props)) {
      props.title = section.title;
    }

    return [
      {
        schema_version: "1.0",
        type: "ui_block",
        action: "create",
        block_id: `report-detail-${runId}-${String(section.id ?? index)}`,
        component: section.component,
        props,
        interactive: false,
        sequence: index,
      },
    ];
  });
}

export function ReportRunDetailPage({ runId }: Props) {
  const { t } = useI18n();
  const { run, isLoading, error } = useReportRun(runId);
  const { payload } = useReportRunPayload(runId);
  const searchParams = useSearchParams();
  const { detail: templateDetail } = useReportTemplate(run?.template_id ?? "", {
    enabled: !!run?.template_id,
  });
  const marketplaceSource = templateDetail?.template?.marketplace_source;
  const payloadBlocks = useMemo(
    () => buildPayloadBlocks(runId, payload),
    [payload, runId],
  );

  useEffect(() => {
    const ctx = decodeCrossPageContext(searchParams);
    if (ctx) logCrossPageNavigation(ctx, "inbound");
  }, [searchParams]);

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading...</div>;
  }

  if (error || !run) {
    return (
      <div className="p-6">
        <Link href="/workspace/report-runs" className="text-sm underline">
          Back to report history
        </Link>
        <div className="mt-4 rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {error ? String(error) : "Report run not found."}
        </div>
      </div>
    );
  }

  const md = run.artifact_paths?.md;
  const pdf = run.artifact_paths?.pdf;

  const ticketSource: CreateTicketSourceContext = {
    source_type: "report",
    source_run_id: run.id,
    source_thread_id: run.thread_id || undefined,
    title: run.template_id
      ? `${t.reportRuns.titlePrefix} ${run.template_id}: ${run.id}`
      : `${t.reportRuns.titlePrefix} ${run.id}`,
    description: run.error_message || undefined,
    device_id: (run.parameters_summary as Record<string, unknown>)?.device_id as string | undefined,
  };

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <SourceBreadcrumb className="mb-1" currentLabel="Report Run" />
          <Link
            href="/workspace/report-runs"
            className="text-muted-foreground text-xs underline-offset-2 hover:underline"
          >
            Back to report history
          </Link>
          {run.thread_id && (
            <Link
              href={pathOfThread(run.thread_id)}
              className="text-muted-foreground ml-3 text-xs underline-offset-2 hover:underline"
            >
              Back to source chat
            </Link>
          )}
          <h1 className="mt-1 font-mono text-lg font-semibold">{run.id}</h1>
          <div className="text-muted-foreground mt-1 text-xs">
            Template{" "}
            {run.template_version != null ? (
              <Link
                className="underline-offset-2 hover:underline"
                href={`/workspace/report-templates/${run.template_id}?version=${run.template_version}`}
              >
                v{run.template_version}
              </Link>
            ) : run.template_version_ref ? (
              <span className="text-muted-foreground">
                {run.template_version_ref}
              </span>
            ) : null}{" "}
            · Status <span className="font-medium">{run.status}</span> · Created{" "}
            {new Date(run.created_at).toLocaleString()}
          </div>
        </div>
        <div className="flex gap-2">
          <CreateClosureTicketDialog
            sourceContext={ticketSource}
            triggerLabel={t.reportRuns.createTicket}
            triggerVariant="outline"
          />
          {md && (
            <a
              className="rounded border px-3 py-1.5 text-sm hover:bg-accent"
              href={artifactUrl(run.thread_id, md)}
              target="_blank"
              rel="noreferrer"
            >
              Download Markdown
            </a>
          )}
          {pdf ? (
            <a
              className="rounded border px-3 py-1.5 text-sm hover:bg-accent"
              href={artifactUrl(run.thread_id, pdf)}
              target="_blank"
              rel="noreferrer"
            >
              Download PDF
            </a>
          ) : run.pdf_skipped_reason ? (
            <span className="rounded border px-3 py-1.5 text-sm text-muted-foreground">
              PDF unavailable ({run.pdf_skipped_reason})
            </span>
          ) : null}
        </div>
      </header>

      {run.error_message && (
        <div
          className={`rounded border p-3 text-sm ${
            getErrorSeverity(run.error_code) === "warning"
              ? "border-amber-500/40 bg-amber-500/10"
              : "border-destructive bg-destructive/10"
          }`}
        >
          <div className="font-medium">{getErrorLabel(run.error_code)}</div>
          <div className="mt-1 text-xs">{run.error_message}</div>
        </div>
      )}

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">Lineage</h2>
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <Link
            className="underline-offset-2 hover:underline"
            href={`/workspace/report-templates/${run.template_id}`}
          >
            Template {run.template_id}
          </Link>
          {marketplaceSource && (
            <Link
              href={`/workspace/template-marketplace/${marketplaceSource.listing_id}`}
              className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 hover:bg-blue-500/20"
            >
              <Store className="h-3 w-3" />
              Marketplace
            </Link>
          )}
          {run.template_version != null && (
            <>
              <span className="text-muted-foreground/50">→</span>
              <Link
                className="underline-offset-2 hover:underline"
                href={`/workspace/report-templates/${run.template_id}?version=${run.template_version}`}
              >
                v{run.template_version}
              </Link>
            </>
          )}
          <span className="text-muted-foreground/50">→</span>
          <span className="font-medium">Run {run.id}</span>
          {run.artifact_paths?.md && (
            <>
              <span className="text-muted-foreground/50">→</span>
              <a
                className="underline-offset-2 hover:underline"
                href={artifactUrl(run.thread_id, run.artifact_paths.md)}
                target="_blank"
                rel="noreferrer"
              >
                report.md
              </a>
            </>
          )}
          {run.artifact_paths?.pdf && (
            <>
              <span className="text-muted-foreground/50">→</span>
              <a
                className="underline-offset-2 hover:underline"
                href={artifactUrl(run.thread_id, run.artifact_paths.pdf)}
                target="_blank"
                rel="noreferrer"
              >
                report.pdf
              </a>
            </>
          )}
        </div>
      </section>

      {run.knowledge_sources && run.knowledge_sources.length > 0 && (
        <section className="rounded border bg-card p-4">
          <h2 className="mb-2 text-sm font-medium">Knowledge Sources</h2>
          <div className="flex flex-col gap-2">
            {run.knowledge_sources.map((ks, i) => (
              <div
                key={i}
                className="text-muted-foreground rounded border bg-muted/30 px-3 py-2 text-xs"
              >
                <span className="font-medium">Source: {ks.source ?? "unknown"}</span>
                {ks.selected_ids && ks.selected_ids.length > 0 && (
                  <div className="mt-1">
                    Selected KBs: {ks.selected_ids.join(", ")}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">Source Chat</h2>
        {run.thread_id ? (
          <Link
            href={pathOfThread(run.thread_id)}
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            Open source conversation
          </Link>
        ) : (
          <span className="text-muted-foreground text-xs">
            No source context available
          </span>
        )}
      </section>

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">{t.reportRuns.linkTicket}</h2>
        <LinkedClosureTickets sourceRunId={run.id} />
      </section>

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">Parameters</h2>
        <pre className="overflow-x-auto text-xs">
          {JSON.stringify(run.parameters_summary, null, 2)}
        </pre>
        {run.parameters_path && (
          <a
            className="mt-2 inline-block text-xs underline-offset-2 hover:underline"
            href={artifactUrl(run.thread_id, run.parameters_path)}
            target="_blank"
            rel="noreferrer"
          >
            Download raw parameters
          </a>
        )}
      </section>

      {run.data_files && run.data_files.length > 0 && (
        <section className="rounded border bg-card p-4">
          <h2 className="mb-2 text-sm font-medium">
            Data Files ({run.data_files.length})
          </h2>
          <ul className="flex flex-col gap-1">
            {run.data_files.map((df: DataFileEntry) => (
              <li key={df.name}>
                <a
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                  href={dataFileArtifactUrl(run.thread_id, df.path)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {df.name}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded border bg-card p-4">
        <h2 className="mb-3 text-sm font-medium">Report Preview</h2>
        {payloadBlocks.length > 0 ? (
          <div className="flex flex-col gap-3">
            {payloadBlocks.map((block) => (
              <GenUIRenderer
                key={block.block_id}
                block={block}
                threadId={run.thread_id}
                disableExpiration={true}
              />
            ))}
          </div>
        ) : (
          <div className="text-muted-foreground text-xs">
            {run.report_payload_path
              ? "Payload loaded, but no renderable sections were found yet."
              : "Payload has not been generated yet."}
          </div>
        )}
      </section>

      <section className="flex-1 overflow-hidden rounded border bg-card p-4">
        <details className="h-full">
          <summary className="cursor-pointer text-sm font-medium">
            Raw report payload
          </summary>
          {payload ? (
            <pre className="mt-3 h-full overflow-auto text-xs">
              {JSON.stringify(payload, null, 2)}
            </pre>
          ) : (
            <div className="text-muted-foreground mt-3 text-xs">
              {run.report_payload_path
                ? "Payload is still loading."
                : "Payload has not been generated yet."}
            </div>
          )}
        </details>
      </section>
    </div>
  );
}
