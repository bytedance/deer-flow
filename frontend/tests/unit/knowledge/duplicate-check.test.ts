/**
 * Duplicate-upload interception pure functions (Task 11): same-name pre-check
 * against the current KB's document list, verdict branching, and copy-name
 * allocation (`name (2).ext`, incrementing on conflict).
 */
import { describe, expect, it } from "@rstest/core";

import {
  findDuplicateByName,
  nextCopyName,
  verdictForDuplicate,
} from "@/core/knowledge/duplicate-check";
import type { KnowledgeDocument } from "@/core/knowledge/types";

function doc(name: string, contentHash: string | null = null): KnowledgeDocument {
  return {
    id: `id-${name}`,
    kb_id: "kb-1",
    uploader_id: "user-1",
    name,
    size_bytes: 100,
    storage_path: `/fake/${name}`,
    status: "ready",
    progress_percent: 100,
    chunk_count: 3,
    error: null,
    path_status: null,
    content_hash: contentHash,
    created_at: "2026-08-14T00:00:00Z",
  };
}

describe("findDuplicateByName", () => {
  it("matches same base name + same extension", () => {
    const documents = [doc("report.pdf"), doc("notes.txt")];
    expect(findDuplicateByName("report.pdf", documents)?.name).toBe("report.pdf");
  });

  it("is case-insensitive on the extension only (base name stays exact)", () => {
    const documents = [doc("report.PDF")];
    expect(findDuplicateByName("report.pdf", documents)?.name).toBe("report.PDF");
    expect(findDuplicateByName("Report.pdf", documents)).toBeUndefined();
  });

  it("does not match same base name with a different extension", () => {
    const documents = [doc("report.pdf")];
    expect(findDuplicateByName("report.docx", documents)).toBeUndefined();
  });

  it("does not match a merely similar name", () => {
    const documents = [doc("report.pdf"), doc("report (2).pdf")];
    expect(findDuplicateByName("report2.pdf", documents)).toBeUndefined();
    expect(findDuplicateByName("my-report.pdf", documents)).toBeUndefined();
  });
});

describe("verdictForDuplicate", () => {
  it("returns clean when no same-name document exists", () => {
    expect(verdictForDuplicate(undefined, "abc")).toEqual({ kind: "clean" });
  });

  it("returns identical when the hashes match", () => {
    const existing = doc("a.txt", "hash-1");
    expect(verdictForDuplicate(existing, "hash-1")).toEqual({ kind: "identical", doc: existing });
  });

  it("returns conflict when the hashes differ", () => {
    const existing = doc("a.txt", "hash-1");
    expect(verdictForDuplicate(existing, "hash-2")).toEqual({ kind: "conflict", doc: existing });
  });

  it("returns conflict when the stored hash is unknown (legacy NULL row)", () => {
    const existing = doc("a.txt", null);
    expect(verdictForDuplicate(existing, "hash-2")).toEqual({ kind: "conflict", doc: existing });
  });
});

describe("nextCopyName", () => {
  it("appends (2) before the extension", () => {
    expect(nextCopyName("report.pdf", new Set(["report.pdf"]))).toBe("report (2).pdf");
  });

  it("increments until the name is free", () => {
    const taken = new Set(["report.pdf", "report (2).pdf", "report (3).pdf"]);
    expect(nextCopyName("report.pdf", taken)).toBe("report (4).pdf");
  });

  it("handles extensionless names", () => {
    expect(nextCopyName("LICENSE", new Set(["LICENSE"]))).toBe("LICENSE (2)");
  });

  it("keeps multi-dot names' last extension", () => {
    expect(nextCopyName("archive.tar.gz", new Set(["archive.tar.gz"]))).toBe("archive.tar (2).gz");
  });
});
