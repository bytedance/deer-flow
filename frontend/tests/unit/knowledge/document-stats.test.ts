/**
 * Pure document-table derivations (spec §3.6 bottom stats row + status
 * classification shared by the badge, polling hook, and stats row).
 */
import { describe, expect, test } from "@rstest/core";

import {
  aggregateDocumentStats,
  DOCUMENTS_POLL_INTERVAL_MS,
  documentsRefetchInterval,
  formatKb,
  formatMb,
  isDocumentTerminal,
} from "@/core/knowledge/document-stats";
import type { KnowledgeDocument } from "@/core/knowledge/types";

function doc(partial: Partial<KnowledgeDocument>): KnowledgeDocument {
  return {
    id: "doc",
    kb_id: "kb",
    uploader_id: "u",
    name: "a.pdf",
    size_bytes: 0,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: null,
    error: null,
    path_status: null,
    content_hash: null,
    created_at: "2026-08-09T10:00:00Z",
    ...partial,
  };
}

describe("aggregateDocumentStats", () => {
  test("aggregates counts, bytes, and chunks client-side", () => {
    const stats = aggregateDocumentStats([
      doc({ id: "a", status: "ready", size_bytes: 100, chunk_count: 5 }),
      doc({
        id: "b",
        status: "indexing",
        size_bytes: 200,
        chunk_count: null,
        progress_percent: 40,
      }),
      doc({
        id: "c",
        status: "failed",
        size_bytes: 300,
        chunk_count: null,
        error: "boom",
      }),
      doc({ id: "d", status: "ready", size_bytes: 50, chunk_count: 7 }),
    ]);
    expect(stats).toEqual({
      total: 4,
      ready: 2,
      failed: 1,
      inProgress: 1,
      totalBytes: 650,
      totalChunks: 12,
    });
  });

  test("treats every non-terminal status as in-progress", () => {
    for (const status of [
      "uploaded",
      "parsing",
      "chunking",
      "indexing",
    ] as const) {
      const stats = aggregateDocumentStats([doc({ status })]);
      expect(stats.inProgress).toBe(1);
      expect(stats.ready).toBe(0);
    }
  });

  test("null chunk_count contributes zero (the em-dash placeholder case)", () => {
    const stats = aggregateDocumentStats([doc({ chunk_count: null })]);
    expect(stats.totalChunks).toBe(0);
  });

  test("empty list yields zeros", () => {
    expect(aggregateDocumentStats([])).toEqual({
      total: 0,
      ready: 0,
      failed: 0,
      inProgress: 0,
      totalBytes: 0,
      totalChunks: 0,
    });
  });
});

describe("isDocumentTerminal", () => {
  test("ready and failed are terminal; pipeline states are not", () => {
    expect(isDocumentTerminal(doc({ status: "ready" }))).toBe(true);
    expect(isDocumentTerminal(doc({ status: "failed" }))).toBe(true);
    expect(isDocumentTerminal(doc({ status: "uploaded" }))).toBe(false);
    expect(isDocumentTerminal(doc({ status: "indexing" }))).toBe(false);
  });
});

describe("documentsRefetchInterval", () => {
  test("polls while any document is mid-pipeline", () => {
    expect(documentsRefetchInterval([doc({ status: "indexing" })])).toBe(
      DOCUMENTS_POLL_INTERVAL_MS,
    );
    expect(documentsRefetchInterval([doc({ status: "uploaded" })])).toBe(
      DOCUMENTS_POLL_INTERVAL_MS,
    );
  });

  test("stops polling when every document is terminal, or data has not loaded", () => {
    expect(
      documentsRefetchInterval([
        doc({ status: "ready" }),
        doc({ status: "failed" }),
      ]),
    ).toBe(false);
    expect(documentsRefetchInterval([])).toBe(false);
    expect(documentsRefetchInterval(undefined)).toBe(false);
  });
});

describe("formatKb（固定 KB，现有）", () => {
  test("<1KB 取整为 1，0 为 0", () => {
    expect(formatKb(0)).toBe("0");
    expect(formatKb(512)).toBe("1");
  });
  test("KB 取整 + 千分位", () => {
    expect(formatKb(2048)).toBe("2");
    expect(formatKb(1536)).toBe("2");
    expect(formatKb(1_572_864)).toBe("1,536");
  });
});

describe("formatMb（固定 MB，新增，2026-09-02 方案 Task 2）", () => {
  test("0 为 0", () => {
    expect(formatMb(0)).toBe("0");
  });
  test(">=0.1MB 保留一位小数", () => {
    expect(formatMb(1_048_576)).toBe("1.0");
    expect(formatMb(1_572_864)).toBe("1.5");
    expect(formatMb(10_485_760)).toBe("10.0");
  });
  test("<0.1MB 保留两位小数（避免显示 0.0）", () => {
    expect(formatMb(52_428)).toBe("0.05");
    expect(formatMb(2048)).toBe("0.00");
  });
});
