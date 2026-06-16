import { describe, expect, it } from "vitest";

import { __test_only } from "@/components/workspace/knowledge-bases/kb-documents-dialog";

const { getDocumentStatusMeta, isDocumentIndexing, buildTrackedDocEntry } =
  __test_only;

describe("getDocumentStatusMeta", () => {
  const t = {
    knowledgeBase: {
      statusPending: "Pending",
      statusIndexing: "Indexing",
      statusError: "Error",
    },
  } as Parameters<typeof getDocumentStatusMeta>[1];

  it("returns null for ready status", () => {
    const result = getDocumentStatusMeta(
      { index_status: "ready" } as Parameters<typeof getDocumentStatusMeta>[0],
      t,
    );
    expect(result).toBeNull();
  });

  it("returns statusPending label for pending status", () => {
    const result = getDocumentStatusMeta(
      { index_status: "pending", index_error: null } as Parameters<
        typeof getDocumentStatusMeta
      >[0],
      t,
    );
    expect(result).toEqual({
      label: "Pending",
      variant: "secondary",
    });
  });

  it("returns statusIndexing label for indexing status", () => {
    const result = getDocumentStatusMeta(
      { index_status: "indexing", index_error: null } as Parameters<
        typeof getDocumentStatusMeta
      >[0],
      t,
    );
    expect(result).toEqual({
      label: "Indexing",
      variant: "secondary",
    });
  });

  it("returns distinct labels for pending vs indexing", () => {
    const pendingResult = getDocumentStatusMeta(
      { index_status: "pending", index_error: null } as Parameters<
        typeof getDocumentStatusMeta
      >[0],
      t,
    );
    const indexingResult = getDocumentStatusMeta(
      { index_status: "indexing", index_error: null } as Parameters<
        typeof getDocumentStatusMeta
      >[0],
      t,
    );
    expect(pendingResult?.label).not.toBe(indexingResult?.label);
    expect(pendingResult?.label).toBe("Pending");
    expect(indexingResult?.label).toBe("Indexing");
  });

  it("returns error label and title for failed status", () => {
    const result = getDocumentStatusMeta(
      {
        index_status: "failed",
        index_error: "Disk full",
      } as Parameters<typeof getDocumentStatusMeta>[0],
      t,
    );
    expect(result).toEqual({
      label: "Error",
      variant: "destructive",
      title: "Disk full",
    });
  });

  it("returns error label with fallback title when index_error is null", () => {
    const result = getDocumentStatusMeta(
      {
        index_status: "failed",
        index_error: null,
      } as Parameters<typeof getDocumentStatusMeta>[0],
      t,
    );
    expect(result?.label).toBe("Error");
    expect(result?.title).toBe("Error");
  });
});

describe("isDocumentIndexing", () => {
  it("returns true for pending", () => {
    expect(isDocumentIndexing("pending")).toBe(true);
  });

  it("returns true for indexing", () => {
    expect(isDocumentIndexing("indexing")).toBe(true);
  });

  it("returns false for indexed", () => {
    expect(isDocumentIndexing("indexed")).toBe(false);
  });

  it("returns false for failed", () => {
    expect(isDocumentIndexing("failed")).toBe(false);
  });
});

describe("buildTrackedDocEntry", () => {
  it("builds entry with trimmed title", () => {
    const entry = buildTrackedDocEntry({ id: "doc-1" }, "  My Doc  ", "file.pdf");
    expect(entry).toEqual({
      id: "doc-1",
      title: "My Doc",
      fileName: "file.pdf",
    });
  });

  it("falls back to fileName when title is empty", () => {
    const entry = buildTrackedDocEntry({ id: "doc-2" }, "   ", "report.pdf");
    expect(entry).toEqual({
      id: "doc-2",
      title: "report.pdf",
      fileName: "report.pdf",
    });
  });

  it("captures fileName independently from title", () => {
    // Critical: title captures the user-provided display name,
    // fileName preserves the original file name for the tracker UI.
    const entry = buildTrackedDocEntry(
      { id: "doc-3" },
      "Custom Name",
      "original.pdf",
    );
    expect(entry.title).toBe("Custom Name");
    expect(entry.fileName).toBe("original.pdf");
  });

  it("preserves distinct id per entry for React key stability", () => {
    const a = buildTrackedDocEntry({ id: "a" }, "Doc A", "a.pdf");
    const b = buildTrackedDocEntry({ id: "b" }, "Doc B", "b.pdf");
    expect(a.id).not.toBe(b.id);
  });
});
