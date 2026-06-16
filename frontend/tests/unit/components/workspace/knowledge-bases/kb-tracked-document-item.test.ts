import { describe, expect, it } from "vitest";

import { __test_only } from "@/components/workspace/knowledge-bases/kb-tracked-document-item";

const { classifyIndexState } = __test_only;

describe("classifyIndexState", () => {
  it("returns isIndexing=true when isPending is true (no data yet)", () => {
    const result = classifyIndexState({ isPending: true });
    expect(result.isIndexing).toBe(true);
    expect(result.isTerminal).toBe(false);
    expect(result.status).toBeUndefined();
  });

  it("returns isIndexing=true when status is pending", () => {
    const result = classifyIndexState({
      data: { index_status: "pending" },
      isPending: false,
    });
    expect(result.isIndexing).toBe(true);
    expect(result.isTerminal).toBe(false);
    expect(result.status).toBe("pending");
  });

  it("returns isIndexing=true when status is indexing", () => {
    const result = classifyIndexState({
      data: { index_status: "indexing" },
      isPending: false,
    });
    expect(result.isIndexing).toBe(true);
    expect(result.isTerminal).toBe(false);
    expect(result.status).toBe("indexing");
  });

  it("returns isTerminal=true when status is indexed", () => {
    const result = classifyIndexState({
      data: { index_status: "indexed" },
      isPending: false,
    });
    expect(result.isIndexing).toBe(false);
    expect(result.isTerminal).toBe(true);
    expect(result.status).toBe("indexed");
  });

  it("returns isTerminal=true when status is failed", () => {
    const result = classifyIndexState({
      data: { index_status: "failed" },
      isPending: false,
    });
    expect(result.isIndexing).toBe(false);
    expect(result.isTerminal).toBe(true);
    expect(result.status).toBe("failed");
  });

  it("returns both false when status is ready (not indexing, not terminal)", () => {
    const result = classifyIndexState({
      data: { index_status: "ready" },
      isPending: false,
    });
    expect(result.isIndexing).toBe(false);
    expect(result.isTerminal).toBe(false);
  });

  it("isPending overrides any status — spinner shows immediately", () => {
    // When isPending is true, status is undefined (no data yet)
    const result = classifyIndexState({ isPending: true });
    expect(result.isIndexing).toBe(true);
  });
});
