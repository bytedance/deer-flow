import { describe, expect, it } from "vitest";

import { __test_only } from "@/core/knowledge-base/hooks";

const {
  getDocumentRefetchInterval,
  getDocumentStatsSignature,
  hasActiveDocumentIndexing,
} = __test_only;

describe("knowledge-base hooks helpers", () => {
  it("treats pending and indexing documents as active indexing work", () => {
    expect(
      hasActiveDocumentIndexing([
        { index_status: "ready" },
        { index_status: "pending" },
      ]),
    ).toBe(true);
    expect(
      hasActiveDocumentIndexing([
        { index_status: "indexing" },
      ]),
    ).toBe(true);
  });

  it("stops polling once all documents are ready or failed", () => {
    expect(
      hasActiveDocumentIndexing([
        { index_status: "ready" },
        { index_status: "failed" },
      ]),
    ).toBe(false);
    expect(getDocumentRefetchInterval([{ index_status: "ready" }])).toBe(false);
  });

  it("returns a polling interval only while indexing is active", () => {
    expect(getDocumentRefetchInterval([{ index_status: "pending" }])).toBe(2000);
    expect(getDocumentRefetchInterval([{ index_status: "indexing" }])).toBe(2000);
    expect(getDocumentRefetchInterval([])).toBe(false);
    expect(getDocumentRefetchInterval(undefined)).toBe(false);
  });

  it("builds a stable signature from document indexing state and chunk counts", () => {
    const signatureA = getDocumentStatsSignature([
      { id: "doc-2", index_status: "ready", chunk_count: 22 },
      { id: "doc-1", index_status: "indexing", chunk_count: 0 },
    ]);
    const signatureB = getDocumentStatsSignature([
      { id: "doc-1", index_status: "indexing", chunk_count: 0 },
      { id: "doc-2", index_status: "ready", chunk_count: 22 },
    ]);

    expect(signatureA).toBe(signatureB);
  });

  it("changes signature when indexing finishes and chunk counts land", () => {
    const pendingSignature = getDocumentStatsSignature([
      { id: "doc-1", index_status: "pending", chunk_count: 0 },
    ]);
    const readySignature = getDocumentStatsSignature([
      { id: "doc-1", index_status: "ready", chunk_count: 22 },
    ]);

    expect(pendingSignature).not.toBe(readySignature);
  });
});
