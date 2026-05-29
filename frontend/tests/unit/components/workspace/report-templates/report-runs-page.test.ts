/**
 * Regression coverage for report-runs page navigation and i18n labels.
 */

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useReportRuns: vi.fn(),
  useReportThreads: vi.fn(),
  useSearchParams: vi.fn(),
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

vi.mock("@/components/ui/tabs", () => ({
  Tabs: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  TabsContent: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  TabsList: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  TabsTrigger: ({ children }: React.PropsWithChildren) =>
    React.createElement("button", null, children),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      reportRuns: {
        pageTitle: "report-history-test",
        pageDescription: "report-history-description-test",
        statusPending: "pending-test",
        statusRunning: "running-test",
        statusSuccess: "success-test",
        statusFailed: "failed-test",
        statusCancelled: "cancelled-test",
        loading: "loading-test",
        loadingFailed: "loading-failed-test",
        emptyRuns: "empty-runs-test",
        emptyChats: "empty-chats-test",
        headerRunId: "run-id-test",
        headerTemplate: "template-test",
        headerVersion: "version-test",
        headerStatus: "status-test",
        headerCreatedAt: "created-at-test",
        headerParams: "params-test",
        headerSourceChat: "source-chat-test",
        tabRuns: "runs-tab-test",
        tabChats: "chats-tab-test",
      },
    },
  }),
}));

vi.mock("@/core/report-templates", () => ({
  useReportRuns: mocks.useReportRuns,
  useReportThreads: mocks.useReportThreads,
}));

vi.mock("@/core/models/navigation", () => ({
  buildCrossPageURL: (path: string) => `${path}?from=mock`,
  logCrossPageNavigation: vi.fn(),
}));

vi.mock("@/core/threads/utils", () => ({
  titleOfThread: (thread: { thread_id: string }) => thread.thread_id,
  pathOfThread: (thread: { thread_id: string } | string) =>
    `/workspace/chats/${typeof thread === "string" ? thread : thread.thread_id}`,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

vi.mock("@/components/workspace/report-templates/thread-action-menu", () => ({
  ThreadActionMenu: () => React.createElement("div", null, "menu"),
}));

import { ReportRunsPage } from "@/components/workspace/report-templates/report-runs-page";

describe("ReportRunsPage", () => {
  it("renders runs tab with source thread column", () => {
    mocks.useSearchParams.mockReturnValue(new URLSearchParams(""));
    mocks.useReportRuns.mockReturnValue({
      runs: [
        {
          id: "rr_001",
          template_id: "tpl_A",
          template_version: 1,
          template_version_ref: null,
          thread_id: "thread-abc-123",
          run_id: "run-xyz",
          status: "success",
          parameters_summary: { k: "v" },
          created_at: "2026-01-01T00:00:00Z",
          artifact_paths: { md: "/mnt/user-data/outputs/report.md" },
          error_code: null,
        },
        {
          id: "rr_002",
          template_id: "tpl_B",
          template_version: null,
          template_version_ref: "builtin-v1",
          thread_id: null as unknown as string,
          run_id: "run-abc",
          status: "failed",
          parameters_summary: {},
          created_at: "2026-01-02T00:00:00Z",
          artifact_paths: {},
          error_code: "DATA_STEP_FAILED",
        },
      ],
      isLoading: false,
      error: null,
    });
    mocks.useReportThreads.mockReturnValue({
      threads: [],
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(React.createElement(ReportRunsPage));

    expect(html).toContain("source-chat-test");
    expect(html).toContain("/workspace/chats/thread-abc-123");
    expect(html).toContain("thread-abc-12");
    expect(html).toContain(">-<");
  });

  it("shows empty state when no runs exist", () => {
    mocks.useSearchParams.mockReturnValue(new URLSearchParams(""));
    mocks.useReportRuns.mockReturnValue({
      runs: [],
      isLoading: false,
      error: null,
    });
    mocks.useReportThreads.mockReturnValue({
      threads: [],
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(React.createElement(ReportRunsPage));

    expect(html).toContain("empty-runs-test");
    expect(html).toContain("empty-chats-test");
  });

  it("renders tab triggers for runs and chats", () => {
    mocks.useSearchParams.mockReturnValue(new URLSearchParams(""));
    mocks.useReportRuns.mockReturnValue({
      runs: [],
      isLoading: false,
      error: null,
    });
    mocks.useReportThreads.mockReturnValue({
      threads: [],
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(React.createElement(ReportRunsPage));

    expect(html).toContain("runs-tab-test");
    expect(html).toContain("chats-tab-test");
  });

  it("shows chats tab when tab=chats search param is set", () => {
    mocks.useSearchParams.mockReturnValue(new URLSearchParams("?tab=chats"));
    mocks.useReportRuns.mockReturnValue({
      runs: [],
      isLoading: false,
      error: null,
    });
    mocks.useReportThreads.mockReturnValue({
      threads: [
        {
          thread_id: "thread-report-1",
          updated_at: "2026-01-15T00:00:00Z",
          metadata: { agent_name: "ai-report--custom" },
        },
      ],
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(React.createElement(ReportRunsPage));

    expect(html).toContain("thread-report-1");
    expect(html).toContain("/workspace/chats/thread-report-1");
  });

  it("shows chats empty state when no report threads", () => {
    mocks.useSearchParams.mockReturnValue(new URLSearchParams("?tab=chats"));
    mocks.useReportRuns.mockReturnValue({
      runs: [],
      isLoading: false,
      error: null,
    });
    mocks.useReportThreads.mockReturnValue({
      threads: [],
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(React.createElement(ReportRunsPage));

    expect(html).toContain("empty-chats-test");
  });
});
