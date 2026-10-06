/**
 * Duplicate-upload action executor (Task 11): the replace branch must delete
 * the old document BEFORE re-uploading (cascade wipes graph/vector/wiki of
 * the old row first), and the copy branch uploads under the allocated copy
 * name without touching the existing row.
 */
import { describe, expect, it, rs } from "@rstest/core";

import { executeDuplicateAction } from "@/core/knowledge/duplicate-upload-flow";
import type { KnowledgeDocument } from "@/core/knowledge/types";

function doc(name: string): KnowledgeDocument {
  return {
    id: "doc-1",
    kb_id: "kb-1",
    uploader_id: "user-1",
    name,
    size_bytes: 100,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: 3,
    error: null,
    path_status: null,
    content_hash: "hash-old",
    created_at: "2026-08-14T00:00:00Z",
  };
}

function ctx(): { file: File; doc: KnowledgeDocument; copyName: string } {
  return {
    file: new File(["new-content"], "report.pdf", { type: "application/pdf" }),
    doc: doc("report.pdf"),
    copyName: "report (2).pdf",
  };
}

describe("executeDuplicateAction", () => {
  it("skip uploads nothing and keeps the old document", async () => {
    const calls: string[] = [];
    const outcome = await executeDuplicateAction("skip", ctx(), {
      deleteDocument: rs.fn(async () => calls.push("delete")),
      uploadFile: rs.fn(async () => calls.push("upload")),
    });
    expect(outcome).toBe("skipped");
    expect(calls).toEqual([]);
  });

  it("cancel uploads nothing either", async () => {
    const calls: string[] = [];
    const outcome = await executeDuplicateAction("cancel", ctx(), {
      deleteDocument: rs.fn(async () => calls.push("delete")),
      uploadFile: rs.fn(async () => calls.push("upload")),
    });
    expect(outcome).toBe("cancelled");
    expect(calls).toEqual([]);
  });

  it("replace deletes first, then uploads the original file", async () => {
    const calls: string[] = [];
    const uploaded: File[] = [];
    const outcome = await executeDuplicateAction("replace", ctx(), {
      deleteDocument: rs.fn(async (docId: string) => {
        calls.push(`delete:${docId}`);
      }),
      uploadFile: rs.fn(async (file: File) => {
        calls.push(`upload:${file.name}`);
        uploaded.push(file);
      }),
    });
    expect(outcome).toBe("replaced");
    // 先删后传：delete must precede upload (cascade contract).
    expect(calls).toEqual(["delete:doc-1", "upload:report.pdf"]);
    expect(uploaded[0]!.name).toBe("report.pdf");
  });

  it("copy uploads under the allocated copy name and never deletes", async () => {
    const calls: string[] = [];
    const uploaded: File[] = [];
    const outcome = await executeDuplicateAction("copy", ctx(), {
      deleteDocument: rs.fn(async () => calls.push("delete")),
      uploadFile: rs.fn(async (file: File) => {
        calls.push(`upload:${file.name}`);
        uploaded.push(file);
      }),
    });
    expect(outcome).toBe("copied");
    expect(calls).toEqual(["upload:report (2).pdf"]);
    // The copy preserves the original bytes and mime type.
    expect(uploaded[0]!.type).toBe("application/pdf");
    expect(await uploaded[0]!.text()).toBe("new-content");
  });
});
