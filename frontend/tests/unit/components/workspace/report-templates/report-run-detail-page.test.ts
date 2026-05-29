import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useSearchParams: vi.fn(),
  useReportRun: vi.fn(),
  useReportRunPayload: vi.fn(),
  useReportTemplate: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("a", props, children),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: mocks.useSearchParams,
}));

vi.mock("@/components/genui/GenUIRenderer", () => ({
  GenUIRenderer: ({ block }: { block: { component: string } }) =>
    React.createElement("div", null, `block:${block.component}`),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      reportRuns: {
        titlePrefix: "[report-test]",
        createTicket: "create-ticket-test",
        linkTicket: "linked-ticket-test",
        runFailed: "run-failed-test",
        templateUnavailable: "template-unavailable-test",
        knowledgeSourceUnavailable: "knowledge-source-unavailable-test",
        runInterrupted: "run-interrupted-test",
        dataStepFailed: "data-step-failed-test",
        detailBreadcrumb: "run-detail-breadcrumb-test",
        backToHistory: "back-history-test",
        backToSourceChat: "back-source-test",
        notFound: "run-not-found-test",
        detailTemplateLabel: "template-label-test",
        detailStatusLabel: "status-label-test",
        detailCreatedLabel: "created-label-test",
        downloadMarkdown: "download-markdown-test",
        downloadPdf: "download-pdf-test",
        pdfUnavailable: "pdf-unavailable-test",
        lineage: "lineage-test",
        lineageTemplatePrefix: "template-prefix-test",
        lineageMarketplace: "marketplace-test",
        lineageRunPrefix: "run-prefix-test",
        knowledgeSources: "knowledge-sources-test",
        knowledgeSourcePrefix: "knowledge-source-prefix-test",
        unknownSource: "unknown-source-test",
        selectedKnowledgeBases: "selected-kbs-test",
        sourceChat: "source-chat-test",
        openSourceConversation: "open-source-test",
        noSourceContext: "no-source-context-test",
        parameters: "parameters-test",
        downloadRawParameters: "download-params-test",
        dataFiles: "data-files-test",
        reportPreview: "report-preview-test",
        previewSectionsMissing: "preview-sections-missing-test",
        previewPayloadMissing: "preview-payload-missing-test",
        rawPayload: "raw-payload-test",
        payloadLoading: "payload-loading-test",
      },
    },
  }),
}));

vi.mock("@/core/report-templates", () => ({
  useReportRun: mocks.useReportRun,
  useReportRunPayload: mocks.useReportRunPayload,
  useReportTemplate: mocks.useReportTemplate,
}));

vi.mock("@/core/threads/utils", () => ({
  pathOfThread: (threadId: string) => `/workspace/chats/${threadId}`,
}));

vi.mock(
  "@/components/workspace/source-breadcrumb",
  () => ({
    SourceBreadcrumb: ({ currentLabel }: { currentLabel?: string }) =>
      React.createElement("div", null, currentLabel),
  }),
);

vi.mock(
  "@/components/workspace/closed-loop/create-closure-ticket-dialog",
  () => ({
    CreateClosureTicketDialog: ({ triggerLabel }: { triggerLabel: string }) =>
      React.createElement("button", null, triggerLabel),
  }),
);

vi.mock(
  "@/components/workspace/closed-loop/linked-closure-tickets",
  () => ({
    LinkedClosureTickets: () => React.createElement("div", null, "tickets"),
  }),
);

import { ReportRunDetailPage } from "@/components/workspace/report-templates/report-run-detail-page";

describe("ReportRunDetailPage", () => {
  it("renders report run detail labels from i18n", () => {
    mocks.useSearchParams.mockReturnValue(new URLSearchParams(""));
    mocks.useReportRun.mockReturnValue({
      run: {
        id: "run_001",
        template_id: "tpl_daily",
        template_version: 5,
        template_version_ref: null,
        thread_id: "thread-123",
        status: "failed",
        created_at: "2026-05-29T03:00:00Z",
        error_code: "DATA_STEP_FAILED",
        error_message: "pipeline exploded",
        parameters_summary: { device_id: "device-7" },
        parameters_path: "/mnt/user-data/params.json",
        report_payload_path: "/mnt/user-data/report.json",
        pdf_skipped_reason: null,
        artifact_paths: {
          md: "/mnt/user-data/report.md",
          pdf: "/mnt/user-data/report.pdf",
        },
        knowledge_sources: [
          {
            source: "kb-main",
            selected_ids: ["kb-1", "kb-2"],
          },
        ],
        data_files: [
          { name: "trend.csv", path: "/mnt/user-data/trend.csv" },
        ],
      },
      isLoading: false,
      error: null,
    });
    mocks.useReportRunPayload.mockReturnValue({
      payload: {
        sections: [
          {
            id: "sec-1",
            title: "Summary",
            component: "markdown",
            props: { body: "hello" },
          },
        ],
      },
    });
    mocks.useReportTemplate.mockReturnValue({
      detail: {
        template: {
          marketplace_source: {
            listing_id: "listing-7",
          },
        },
      },
    });

    const html = renderToStaticMarkup(
      React.createElement(ReportRunDetailPage, { runId: "run_001" }),
    );

    expect(html).toContain("run-detail-breadcrumb-test");
    expect(html).toContain("back-history-test");
    expect(html).toContain("back-source-test");
    expect(html).toContain("template-label-test");
    expect(html).toContain("status-label-test");
    expect(html).toContain("created-label-test");
    expect(html).toContain("download-markdown-test");
    expect(html).toContain("download-pdf-test");
    expect(html).toContain("lineage-test");
    expect(html).toContain("marketplace-test");
    expect(html).toContain("knowledge-sources-test");
    expect(html).toContain("source-chat-test");
    expect(html).toContain("parameters-test");
    expect(html).toContain("data-files-test");
    expect(html).toContain("report-preview-test");
    expect(html).toContain("raw-payload-test");
    expect(html).toContain("data-step-failed-test");
    expect(html).not.toContain("Back to report history");
    expect(html).not.toContain("Download Markdown");
    expect(html).not.toContain("Knowledge Sources");
    expect(html).not.toContain("Raw report payload");
  });
});
