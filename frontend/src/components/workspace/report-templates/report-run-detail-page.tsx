"use client";

import { Store } from "@/components/ui/icons";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { GenUIRenderer } from "@/components/genui/GenUIRenderer";
import { BlockPersistProvider } from "@/core/genui/block-persist-context";
import type { UIBlock } from "@/core/genui/store";
import { useI18n } from "@/core/i18n/hooks";
import {
  decodeCrossPageContext,
  logCrossPageNavigation,
} from "@/core/models/navigation";
import type { DataFileEntry } from "@/core/report-templates";
import { updateReportRunPayload, useReportRun, useReportRunPayload, useReportTemplate } from "@/core/report-templates";
import { pathOfThread } from "@/core/threads/utils";

import { CreateClosureTicketDialog } from "../closed-loop/create-closure-ticket-dialog";
import type { CreateTicketSourceContext } from "../closed-loop/create-closure-ticket-dialog";
import { LinkedClosureTickets } from "../closed-loop/linked-closure-tickets";
import { SourceBreadcrumb } from "../source-breadcrumb";

interface Props {
  runId: string;
}

type PayloadSection = {
  id?: string | number;
  title?: string;
  component?: string;
  props?: Record<string, unknown>;
};

type ErrorSeverity = "destructive" | "warning";

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

function getErrorSeverity(errorCode: string | null | undefined): ErrorSeverity {
  if (!errorCode) return "destructive";
  if (errorCode.startsWith("TEMPLATE_UNAVAILABLE")) return "warning";
  return "destructive";
}

function getErrorLabel(
  errorCode: string | null | undefined,
  labels: {
    runFailed: string;
    templateUnavailable: string;
    knowledgeSourceUnavailable: string;
    runInterrupted: string;
    dataStepFailed: string;
  },
): string {
  if (!errorCode) return labels.runFailed;
  if (errorCode.startsWith("TEMPLATE_UNAVAILABLE")) return labels.templateUnavailable;
  if (errorCode.startsWith("KB_UNAVAILABLE")) return labels.knowledgeSourceUnavailable;
  if (errorCode.startsWith("RUN_INTERRUPTED")) return labels.runInterrupted;
  if (errorCode.startsWith("DATA_STEP_FAILED")) return labels.dataStepFailed;
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
  const queryClient = useQueryClient();
  const { run, isLoading, error } = useReportRun(runId);
  const { payload } = useReportRunPayload(runId);
  const searchParams = useSearchParams();
  const { detail: templateDetail } = useReportTemplate(run?.template_id ?? "");
  const marketplaceSource = templateDetail?.template?.marketplace_source;
  const payloadBlocks = useMemo(
    () => buildPayloadBlocks(runId, payload),
    [payload, runId],
  );

  const payloadRef = useRef(payload);
  payloadRef.current = payload;

  const handleSaveContent = useCallback(
    async (blockId: string, content: string) => {
      const current = payloadRef.current;
      const sections = current?.sections as PayloadSection[] | undefined;
      if (!sections) throw new Error("No sections in payload");

      // blockId format: report-detail-{runId}-{sectionId}
      const prefix = `report-detail-${runId}-`;
      if (!blockId.startsWith(prefix)) throw new Error("Unknown blockId format");
      const sectionKey = blockId.slice(prefix.length);

      const updated = sections.map((section, index) => {
        const key = String(section.id ?? index);
        if (key !== sectionKey) return section;
        return {
          ...section,
          props: { ...(section.props ?? {}), content },
        };
      });

      await updateReportRunPayload(runId, updated);
      queryClient.invalidateQueries({ queryKey: ["report-runs", "payload", runId] });
    },
    [runId, queryClient],
  );

  useEffect(() => {
    const ctx = decodeCrossPageContext(searchParams);
    if (ctx) logCrossPageNavigation(ctx, "inbound");
  }, [searchParams]);

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        {t.reportRuns.loading}
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="p-6">
        <Link href="/workspace/report-runs" className="text-sm underline">
          {t.reportRuns.backToHistory}
        </Link>
        <div className="mt-4 rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {error ? String(error) : t.reportRuns.notFound}
        </div>
      </div>
    );
  }

  const md = run.artifact_paths?.md;
  const pdf = run.artifact_paths?.pdf;
  const threadId = run.thread_id ?? "";

  const ticketSource: CreateTicketSourceContext = {
    source_type: "report",
    source_run_id: run.id,
    source_thread_id: run.thread_id,
    title: run.template_id
      ? `${t.reportRuns.titlePrefix} ${run.template_id}: ${run.id}`
      : `${t.reportRuns.titlePrefix} ${run.id}`,
    description: run.error_message ?? undefined,
    device_id:
      typeof run.parameters_summary.device_id === "string"
        ? run.parameters_summary.device_id
        : undefined,
  };

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <SourceBreadcrumb
            className="mb-1"
            currentLabel={t.reportRuns.detailBreadcrumb}
          />
          <Link
            href="/workspace/report-runs"
            className="text-muted-foreground text-xs underline-offset-2 hover:underline"
          >
            {t.reportRuns.backToHistory}
          </Link>
          {run.thread_id && (
            <Link
              href={pathOfThread(run.thread_id)}
              className="text-muted-foreground ml-3 text-xs underline-offset-2 hover:underline"
            >
              {t.reportRuns.backToSourceChat}
            </Link>
          )}
          <h1 className="mt-1 font-mono text-lg font-semibold">{run.id}</h1>
          <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-1 text-xs">
            <span>{t.reportRuns.detailTemplateLabel}</span>
            {run.template_version != null ? (
              <Link
                className="underline-offset-2 hover:underline"
                href={`/workspace/report-templates/${run.template_id}?version=${run.template_version}`}
              >
                v{run.template_version}
              </Link>
            ) : run.template_version_ref ? (
              <span>{run.template_version_ref}</span>
            ) : (
              <span>{run.template_id}</span>
            )}
            <span className="text-muted-foreground/50">/</span>
            <span>
              {t.reportRuns.detailStatusLabel}{" "}
              <span className="font-medium">{run.status}</span>
            </span>
            <span className="text-muted-foreground/50">/</span>
            <span>
              {t.reportRuns.detailCreatedLabel}{" "}
              {new Date(run.created_at).toLocaleString()}
            </span>
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
              href={artifactUrl(threadId, md)}
              target="_blank"
              rel="noreferrer"
            >
              {t.reportRuns.downloadMarkdown}
            </a>
          )}
          {pdf ? (
            <a
              className="rounded border px-3 py-1.5 text-sm hover:bg-accent"
              href={artifactUrl(threadId, pdf)}
              target="_blank"
              rel="noreferrer"
            >
              {t.reportRuns.downloadPdf}
            </a>
          ) : run.pdf_skipped_reason ? (
            <span className="rounded border px-3 py-1.5 text-sm text-muted-foreground">
              {t.reportRuns.pdfUnavailable} ({run.pdf_skipped_reason})
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
          <div className="font-medium">
            {getErrorLabel(run.error_code, t.reportRuns)}
          </div>
          <div className="mt-1 text-xs">{run.error_message}</div>
        </div>
      )}

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">{t.reportRuns.lineage}</h2>
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <Link
            className="underline-offset-2 hover:underline"
            href={`/workspace/report-templates/${run.template_id}`}
          >
            {t.reportRuns.lineageTemplatePrefix} {run.template_id}
          </Link>
          {marketplaceSource && (
            <Link
              href={`/workspace/template-marketplace/${marketplaceSource.listing_id}`}
              className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 hover:bg-blue-500/20"
            >
              <Store className="h-3 w-3" />
              {t.reportRuns.lineageMarketplace}
            </Link>
          )}
          {run.template_version != null && (
            <>
              <span className="text-muted-foreground/50">/</span>
              <Link
                className="underline-offset-2 hover:underline"
                href={`/workspace/report-templates/${run.template_id}?version=${run.template_version}`}
              >
                v{run.template_version}
              </Link>
            </>
          )}
          <span className="text-muted-foreground/50">/</span>
          <span className="font-medium">
            {t.reportRuns.lineageRunPrefix} {run.id}
          </span>
          {run.artifact_paths?.md && (
            <>
              <span className="text-muted-foreground/50">/</span>
              <a
                className="underline-offset-2 hover:underline"
                href={artifactUrl(threadId, run.artifact_paths.md)}
                target="_blank"
                rel="noreferrer"
              >
                report.md
              </a>
            </>
          )}
          {run.artifact_paths?.pdf && (
            <>
              <span className="text-muted-foreground/50">/</span>
              <a
                className="underline-offset-2 hover:underline"
                href={artifactUrl(threadId, run.artifact_paths.pdf)}
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
          <h2 className="mb-2 text-sm font-medium">
            {t.reportRuns.knowledgeSources}
          </h2>
          <div className="flex flex-col gap-2">
            {run.knowledge_sources.map((ks, i) => (
              <div
                key={i}
                className="text-muted-foreground rounded border bg-muted/30 px-3 py-2 text-xs"
              >
                <span className="font-medium">
                  {t.reportRuns.knowledgeSourcePrefix}:{" "}
                  {ks.source ?? t.reportRuns.unknownSource}
                </span>
                {ks.selected_ids && ks.selected_ids.length > 0 && (
                  <div className="mt-1">
                    {t.reportRuns.selectedKnowledgeBases}:{" "}
                    {ks.selected_ids.join(", ")}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">{t.reportRuns.sourceChat}</h2>
        {run.thread_id ? (
          <Link
            href={pathOfThread(run.thread_id)}
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {t.reportRuns.openSourceConversation}
          </Link>
        ) : (
          <span className="text-muted-foreground text-xs">
            {t.reportRuns.noSourceContext}
          </span>
        )}
      </section>

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">{t.reportRuns.linkTicket}</h2>
        <LinkedClosureTickets sourceRunId={run.id} />
      </section>

      <section className="rounded border bg-card p-4">
        <h2 className="mb-2 text-sm font-medium">{t.reportRuns.parameters}</h2>
        <pre className="overflow-x-auto text-xs">
          {JSON.stringify(run.parameters_summary, null, 2)}
        </pre>
        {run.parameters_path && (
          <a
            className="mt-2 inline-block text-xs underline-offset-2 hover:underline"
            href={artifactUrl(threadId, run.parameters_path)}
            target="_blank"
            rel="noreferrer"
          >
            {t.reportRuns.downloadRawParameters}
          </a>
        )}
      </section>

      {run.data_files && run.data_files.length > 0 && (
        <section className="rounded border bg-card p-4">
          <h2 className="mb-2 text-sm font-medium">
            {t.reportRuns.dataFiles} ({run.data_files.length})
          </h2>
          <ul className="flex flex-col gap-1">
            {run.data_files.map((df: DataFileEntry) => (
              <li key={df.name}>
                <a
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                  href={dataFileArtifactUrl(threadId, df.path)}
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
        <h2 className="mb-3 text-sm font-medium">
          {t.reportRuns.reportPreview}
        </h2>
        {payloadBlocks.length > 0 ? (
          <BlockPersistProvider saveContent={handleSaveContent}>
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
          </BlockPersistProvider>
        ) : (
          <div className="text-muted-foreground text-xs">
            {run.report_payload_path
              ? t.reportRuns.previewSectionsMissing
              : t.reportRuns.previewPayloadMissing}
          </div>
        )}
      </section>

      <section className="flex-1 overflow-hidden rounded border bg-card p-4">
        <details className="h-full">
          <summary className="cursor-pointer text-sm font-medium">
            {t.reportRuns.rawPayload}
          </summary>
          {payload ? (
            <pre className="mt-3 h-full overflow-auto text-xs">
              {JSON.stringify(payload, null, 2)}
            </pre>
          ) : (
            <div className="text-muted-foreground mt-3 text-xs">
              {run.report_payload_path
                ? t.reportRuns.payloadLoading
                : t.reportRuns.previewPayloadMissing}
            </div>
          )}
        </details>
      </section>
    </div>
  );
}
