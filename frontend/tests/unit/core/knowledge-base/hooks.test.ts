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
        { index_status: "indexed" },
        { index_status: "pending" },
      ]),
    ).toBe(true);
    expect(
      hasActiveDocumentIndexing([
        { index_status: "indexing" },
      ]),
    ).toBe(true);
  });

  it("stops polling once all documents are indexed or failed", () => {
    expect(
      hasActiveDocumentIndexing([
        { index_status: "indexed" },
        { index_status: "failed" },
      ]),
    ).toBe(false);
    expect(getDocumentRefetchInterval([{ index_status: "indexed" }])).toBe(false);
  });

  it("returns a polling interval only while indexing is active", () => {
    expect(getDocumentRefetchInterval([{ index_status: "pending" }])).toBe(2000);
    expect(getDocumentRefetchInterval([{ index_status: "indexing" }])).toBe(2000);
    expect(getDocumentRefetchInterval([{ index_status: "failed" }])).toBe(false);
    expect(getDocumentRefetchInterval([])).toBe(false);
    expect(getDocumentRefetchInterval(undefined)).toBe(false);
  });

  it("returns active interval for mixed list with at least one pending or indexing doc", () => {
    expect(
      getDocumentRefetchInterval([
        { index_status: "indexed" },
        { index_status: "pending" },
        { index_status: "failed" },
      ]),
    ).toBe(2000);
    expect(
      getDocumentRefetchInterval([
        { index_status: "indexed" },
        { index_status: "indexing" },
        { index_status: "indexed" },
      ]),
    ).toBe(2000);
  });

  it("builds a stable signature from document indexing state and chunk counts", () => {
    const signatureA = getDocumentStatsSignature([
      { id: "doc-2", index_status: "indexed", chunk_count: 22 },
      { id: "doc-1", index_status: "indexing", chunk_count: 0 },
    ]);
    const signatureB = getDocumentStatsSignature([
      { id: "doc-1", index_status: "indexing", chunk_count: 0 },
      { id: "doc-2", index_status: "indexed", chunk_count: 22 },
    ]);

    expect(signatureA).toBe(signatureB);
  });

  it("changes signature when indexing finishes and chunk counts land", () => {
    const pendingSignature = getDocumentStatsSignature([
      { id: "doc-1", index_status: "pending", chunk_count: 0 },
    ]);
    const indexedSignature = getDocumentStatsSignature([
      { id: "doc-1", index_status: "indexed", chunk_count: 22 },
    ]);

    expect(pendingSignature).not.toBe(indexedSignature);
  });
});
