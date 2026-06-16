/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const summaryMocks = vi.hoisted(() => ({
  state: {
    isLoading: false,
    summary: {
      total_kbs: 1,
      index_success_rate: 1,
      failure_by_type: {
        parsing: 1,
      },
      documents: {
        total: 2,
        ready: 2,
        pending: 0,
        indexing: 0,
        failed: 0,
        cancelled: 0,
      },
      retrieval: {
        avg_latency_ms: 123,
        p95_latency_ms: 456,
        total_queries: 3,
      },
      recent_failures: [
        {
          job_id: "job-1",
          doc_id: "doc-1",
          error: null,
          finished_at: null,
        },
      ],
      per_kb: [
        {
          kb_id: "kb-1",
          kb_name: "测试知识库",
          total: 2,
          ready: 2,
          failed: 0,
          avg_retrieval_latency_ms: 123,
          total_queries: 3,
        },
      ],
    },
  },
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      knowledgeBase: {
        title: "知识库",
        name: "名称",
        documents: "文档",
        indexedCount: "已索引",
        failedCount: "失败",
        totalQueries: "查询次数",
        retrievalLatencyAvg: "平均延迟",
        healthSummaryLoading: "正在加载健康概览...",
        healthSummaryEmpty: "暂无知识库健康数据",
        healthSummaryIndexSuccess: "索引成功率",
        healthSummaryDocumentsCount: (ready: number, total: number) =>
          `${ready} / ${total} 篇文档`,
        healthSummaryRetrievalP95: "检索 P95",
        healthSummaryQueriesAcross: (queries: number, totalKbs: number) =>
          `${queries} 次查询，覆盖 ${totalKbs} 个知识库`,
        healthSummaryIndexingInProgress: (count: number) =>
          `${count} 个索引中`,
        healthSummaryAllIdle: "全部空闲",
        healthSummaryFailedDocs: "失败文档",
        healthSummaryErrorCategories: (count: number) =>
          `${count} 类错误`,
        healthSummaryFailureByType: "按类型统计失败",
        healthSummaryRecentFailures: (count: number) =>
          `最近失败 (${count})`,
        healthSummaryUnknownError: "未知错误",
        healthSummaryPerKnowledgeBase: "各知识库明细",
      },
    },
  }),
}));

vi.mock("@/core/knowledge-base", () => ({
  useHealthSummary: () => ({
    data: summaryMocks.state.summary,
    isLoading: summaryMocks.state.isLoading,
  }),
}));

import { KbHealthSummary } from "@/components/workspace/knowledge-bases/kb-health-summary";

describe("KbHealthSummary", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    summaryMocks.state.isLoading = false;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("renders the loading copy from i18n", () => {
    summaryMocks.state.isLoading = true;

    React.act(() => {
      root.render(React.createElement(KbHealthSummary));
    });

    expect(container.textContent).toContain("正在加载健康概览...");
    expect(container.textContent).not.toContain("Loading health summary...");
  });

  it("renders health metric labels from i18n instead of hard-coded English strings", () => {
    React.act(() => {
      root.render(React.createElement(KbHealthSummary));
    });

    expect(container.textContent).toContain("索引成功率");
    expect(container.textContent).toContain("检索 P95");
    expect(container.textContent).toContain("3 次查询，覆盖 1 个知识库");
    expect(container.textContent).toContain("失败文档");
    expect(container.textContent).toContain("按类型统计失败");
    expect(container.textContent).toContain("最近失败 (1)");
    expect(container.textContent).toContain("未知错误");
    expect(container.textContent).toContain("各知识库明细");
    expect(container.textContent).toContain("名称");
    expect(container.textContent).toContain("平均延迟");
    expect(container.textContent).not.toContain("Index Success");
    expect(container.textContent).not.toContain("Per Knowledge Base");
  });
});
