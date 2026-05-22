import { describe, expect, it } from "vitest";

import { __test_only } from "@/core/knowledge-base/hooks";

const { hasActiveDocumentIndexing, getDocumentRefetchInterval } = __test_only;

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
});
