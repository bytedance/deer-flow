import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/knowledge/api", () => ({
  listDocuments: rs.fn(),
  uploadDocument: rs.fn(),
}));

import * as api from "@/core/knowledge/api";
import type { KnowledgeDocument } from "@/core/knowledge/types";
import { importThreadToKnowledgeBase } from "@/core/threads/import-to-knowledge-base";
import type { AgentThread } from "@/core/threads/types";

function makeThread(): AgentThread {
  return {
    thread_id: "thread-1",
    created_at: "2026-05-21T00:00:00Z",
    updated_at: "2026-05-21T00:00:00Z",
    metadata: {},
    status: "idle",
    values: { messages: [], title: "Demo thread" },
  } as unknown as AgentThread;
}

function human(content: string): Message {
  return { id: `h-${content}`, type: "human", content } as Message;
}

function ai(content: string): Message {
  return { id: `a-${content}`, type: "ai", content } as Message;
}

function docNamed(name: string): KnowledgeDocument {
  return {
    id: `doc-${name}`,
    kb_id: "kb-1",
    uploader_id: "user-1",
    name,
    size_bytes: 10,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: 1,
    error: null,
    path_status: null,
    content_hash: null,
    created_at: "2026-05-21T00:00:00Z",
  };
}

function uploadedFile(): File {
  const call = rs.mocked(api.uploadDocument).mock.calls[0];
  expect(call).toBeDefined();
  return call![1];
}

afterEach(() => {
  rs.clearAllMocks();
});

describe("importThreadToKnowledgeBase", () => {
  it("uploads the formatted transcript as <title>.md when the name is free", async () => {
    rs.mocked(api.listDocuments).mockResolvedValue([]);
    rs.mocked(api.uploadDocument).mockResolvedValue(docNamed("Demo thread.md"));

    const result = await importThreadToKnowledgeBase(
      makeThread(),
      [human("hello"), ai("hi there")],
      "kb-1",
    );

    expect(api.uploadDocument).toHaveBeenCalledTimes(1);
    expect(rs.mocked(api.uploadDocument).mock.calls[0]?.[0]).toBe("kb-1");
    const file = uploadedFile();
    expect(file.name).toBe("Demo thread.md");
    expect(file.type).toBe("text/markdown;charset=utf-8");
    const text = await file.text();
    expect(text).toContain("# Demo thread");
    expect(text).toContain("hello");
    expect(text).toContain("hi there");
    expect(result).toEqual({ documentName: "Demo thread.md", renamed: false });
  });

  it("allocates a ` (2)` copy suffix when the title collides", async () => {
    rs.mocked(api.listDocuments).mockResolvedValue([
      docNamed("Demo thread.md"),
    ]);
    rs.mocked(api.uploadDocument).mockResolvedValue(
      docNamed("Demo thread (2).md"),
    );

    const result = await importThreadToKnowledgeBase(
      makeThread(),
      [human("hello")],
      "kb-1",
    );

    expect(uploadedFile().name).toBe("Demo thread (2).md");
    expect(result).toEqual({
      documentName: "Demo thread (2).md",
      renamed: true,
    });
  });

  it("increments the suffix past existing copies", async () => {
    rs.mocked(api.listDocuments).mockResolvedValue([
      docNamed("Demo thread.md"),
      docNamed("Demo thread (2).md"),
    ]);
    rs.mocked(api.uploadDocument).mockResolvedValue(
      docNamed("Demo thread (3).md"),
    );

    const result = await importThreadToKnowledgeBase(
      makeThread(),
      [human("hello")],
      "kb-1",
    );

    expect(uploadedFile().name).toBe("Demo thread (3).md");
    expect(result.renamed).toBe(true);
  });

  it("propagates upload failures without swallowing them", async () => {
    rs.mocked(api.listDocuments).mockResolvedValue([]);
    rs.mocked(api.uploadDocument).mockRejectedValue(new Error("boom"));

    await expect(
      importThreadToKnowledgeBase(makeThread(), [human("hello")], "kb-1"),
    ).rejects.toThrow("boom");
  });
});
