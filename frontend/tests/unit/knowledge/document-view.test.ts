/**
 * Client-side view helpers for the document list toolbar (spec §5.2):
 * name filter + column sort. The list endpoint returns full collections,
 * so both stay client-side.
 */
import { describe, expect, it } from "@rstest/core";

import {
  filterDocuments,
  sortDocuments,
} from "@/core/knowledge/document-view";
import type { KnowledgeDocument } from "@/core/knowledge/types";

function doc(partial: Partial<KnowledgeDocument>): KnowledgeDocument {
  return {
    id: "doc-1",
    kb_id: "kb-1",
    uploader_id: "user-1",
    name: "文档.pdf",
    size_bytes: 1024,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: 10,
    error: null,
    path_status: null,
    content_hash: null,
    created_at: "2026-08-09T10:00:00Z",
    ...partial,
  };
}

describe("filterDocuments", () => {
  const docs = [
    doc({ id: "a", name: "产品手册.pdf" }),
    doc({ id: "b", name: "Roadmap 2026.md" }),
    doc({ id: "c", name: "研发规范.docx" }),
  ];

  it("returns everything for a blank query", () => {
    expect(filterDocuments(docs, "")).toHaveLength(3);
    expect(filterDocuments(docs, "   ")).toHaveLength(3);
  });

  it("matches by name case-insensitively", () => {
    expect(filterDocuments(docs, "roadmap").map((d) => d.id)).toEqual(["b"]);
    expect(filterDocuments(docs, "ROADMAP").map((d) => d.id)).toEqual(["b"]);
    expect(filterDocuments(docs, "研发").map((d) => d.id)).toEqual(["c"]);
  });

  it("returns an empty list when nothing matches", () => {
    expect(filterDocuments(docs, "不存在")).toEqual([]);
  });
});

describe("sortDocuments", () => {
  const docs = [
    doc({ id: "a", name: "乙.pdf", size_bytes: 4096, created_at: "2026-08-08T10:00:00Z" }),
    doc({ id: "b", name: "甲.pdf", size_bytes: 1024, created_at: "2026-08-09T09:00:00Z" }),
    doc({ id: "c", name: "丙.pdf", size_bytes: 2048, chunk_count: null, created_at: "2026-08-09T10:00:00Z" }),
  ];

  it("sorts by created_at descending by default semantics", () => {
    expect(sortDocuments(docs, "created_at", "desc").map((d) => d.id)).toEqual(["c", "b", "a"]);
    expect(sortDocuments(docs, "created_at", "asc").map((d) => d.id)).toEqual(["a", "b", "c"]);
  });

  it("sorts by name and by numeric size in both directions", () => {
    // localeCompare orders Chinese names by pinyin (丙 bǐng < 甲 jiǎ < 乙 yǐ)
    expect(sortDocuments(docs, "name", "asc").map((d) => d.name)).toEqual(["丙.pdf", "甲.pdf", "乙.pdf"]);
    expect(sortDocuments(docs, "size_bytes", "asc").map((d) => d.id)).toEqual(["b", "c", "a"]);
    expect(sortDocuments(docs, "size_bytes", "desc").map((d) => d.id)).toEqual(["a", "c", "b"]);
  });

  it("sinks null chunk counts to the bottom in both directions", () => {
    const withCounts = [
      doc({ id: "x", chunk_count: 3 }),
      doc({ id: "y", chunk_count: null }),
      doc({ id: "z", chunk_count: 8 }),
    ];
    expect(sortDocuments(withCounts, "chunk_count", "asc").map((d) => d.id)).toEqual(["x", "z", "y"]);
    expect(sortDocuments(withCounts, "chunk_count", "desc").map((d) => d.id)).toEqual(["z", "x", "y"]);
  });

  it("does not mutate the input array", () => {
    const input = [doc({ id: "a", size_bytes: 2 }), doc({ id: "b", size_bytes: 1 })];
    sortDocuments(input, "size_bytes", "asc");
    expect(input.map((d) => d.id)).toEqual(["a", "b"]);
  });
});
