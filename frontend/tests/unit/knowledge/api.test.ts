/**
 * Contract tests for the knowledge-base REST client (spec §5.3, Phase-1
 * subset). Pins method/path/body wiring against the Task-8 gateway router;
 * the fetcher layer (CSRF, credentials, 401 redirect) is mocked and covered
 * by its own tests.
 */
import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://gw",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  createKnowledgeBase,
  deleteDocument,
  deleteKnowledgeBase,
  getKnowledgeBase,
  getReindexStatus,
  getSupportedFormats,
  listDocuments,
  listDocumentChunks,
  listKnowledgeBases,
  reindexKnowledgeBase,
  retryDocument,
  updateKnowledgeBase,
  uploadDocument,
} from "@/core/knowledge/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const KB = {
  id: "kb-1",
  owner_id: "user-1",
  name: "产品资料",
  description: "d",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};

const DOC = {
  id: "doc-1",
  kb_id: "kb-1",
  uploader_id: "user-1",
  name: "手册.pdf",
  size_bytes: 2048,
  storage_path: "/data/knowledge/kb-1/doc-1/手册.pdf",
  status: "ready",
  progress_percent: 100,
  chunk_count: 12,
  error: null,
  created_at: "2026-08-09T10:01:00Z",
};

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("knowledge-base endpoints", () => {
  test("listKnowledgeBases GETs the bare list", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, [KB]));
    const result = await listKnowledgeBases();
    expect(mockedFetch).toHaveBeenCalledWith("http://gw/api/knowledge-bases");
    expect(result).toEqual([KB]);
  });

  test("createKnowledgeBase POSTs name/description and parses 201", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(201, KB));
    const result = await createKnowledgeBase({ name: "产品资料", description: "d" });
    const [url, init] = mockedFetch.mock.calls[0]!;
    expect(url).toBe("http://gw/api/knowledge-bases");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      name: "产品资料",
      description: "d",
    });
    expect(result).toEqual(KB);
  });

  test("getKnowledgeBase GETs the detail route", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, KB));
    const result = await getKnowledgeBase("kb-1");
    expect(mockedFetch).toHaveBeenCalledWith("http://gw/api/knowledge-bases/kb-1");
    expect(result.name).toBe("产品资料");
  });

  test("updateKnowledgeBase PATCHes only provided fields", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { ...KB, name: "新名" }));
    const result = await updateKnowledgeBase("kb-1", { name: "新名" });
    const [url, init] = mockedFetch.mock.calls[0]!;
    expect(url).toBe("http://gw/api/knowledge-bases/kb-1");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(init?.body as string)).toEqual({ name: "新名" });
    expect(result.name).toBe("新名");
  });

  test("deleteKnowledgeBase issues DELETE and tolerates an empty 204 body", async () => {
    mockedFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(deleteKnowledgeBase("kb-1")).resolves.toBeUndefined();
    expect(mockedFetch.mock.calls[0]![1]?.method).toBe("DELETE");
  });

  test("surfaces backend detail on failure", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(403, { detail: "你没有访问该知识库的权限" }));
    await expect(listKnowledgeBases()).rejects.toThrow("你没有访问该知识库的权限");
  });

});

describe("document endpoints", () => {
  test("listDocuments GETs the bare list", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, [DOC]));
    const result = await listDocuments("kb-1");
    expect(mockedFetch).toHaveBeenCalledWith("http://gw/api/knowledge-bases/kb-1/documents");
    expect(result[0]!.status).toBe("ready");
  });

  test("uploadDocument POSTs multipart form data with the file part", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(202, DOC));
    const file = new File(["pdf-bytes"], "手册.pdf", { type: "application/pdf" });
    const result = await uploadDocument("kb-1", file);
    const [url, init] = mockedFetch.mock.calls[0]!;
    expect(url).toBe("http://gw/api/knowledge-bases/kb-1/documents");
    expect(init?.method).toBe("POST");
    const body = init?.body as FormData;
    expect(body.get("file")).toBeInstanceOf(File);
    expect((body.get("file") as File).name).toBe("手册.pdf");
    // multipart must let fetch set its own boundary header
    expect((init?.headers as Record<string, string> | undefined)?.["Content-Type"]).toBeUndefined();
    expect(result.status).toBe("ready");
  });

  test("deleteDocument issues DELETE on the nested route", async () => {
    mockedFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteDocument("kb-1", "doc-1");
    expect(mockedFetch).toHaveBeenCalledWith(
      "http://gw/api/knowledge-bases/kb-1/documents/doc-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  test("retryDocument POSTs the retry route and parses 202", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(202, { ...DOC, status: "uploaded", progress_percent: 0, error: null }),
    );
    const result = await retryDocument("kb-1", "doc-1");
    expect(mockedFetch.mock.calls[0]![0]).toBe(
      "http://gw/api/knowledge-bases/kb-1/documents/doc-1/retry",
    );
    expect(mockedFetch.mock.calls[0]![1]?.method).toBe("POST");
    expect(result.status).toBe("uploaded");
  });

  test("listDocumentChunks encodes pagination params", async () => {
    const page = {
      items: [
        {
          chunk_id: "doc-1#0000",
          doc_id: "doc-1",
          kb_id: "kb-1",
          chunk_index: 0,
          text: "切片文本",
          heading_path: ["第一章"],
          page: 3,
          token_count: 512,
          entities: ["DeerFlow"],
          extract_status: "done",
        },
      ],
      total: 1,
      offset: 40,
      limit: 20,
    };
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, page));
    const result = await listDocumentChunks("kb-1", "doc-1", { offset: 40, limit: 20 });
    expect(mockedFetch).toHaveBeenCalledWith(
      "http://gw/api/knowledge-bases/kb-1/documents/doc-1/chunks?offset=40&limit=20",
    );
    expect(result.total).toBe(1);
    expect(result.items[0]!.entities).toEqual(["DeerFlow"]);
  });
});

describe("supported formats endpoint", () => {
  test("getSupportedFormats fetches the allowlist (Task 6)", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { suffixes: [".md", ".txt"] }));
    const result = await getSupportedFormats();
    expect(mockedFetch).toHaveBeenCalledWith("http://gw/api/knowledge-bases/supported-formats");
    expect(result.suffixes).toEqual([".md", ".txt"]);
  });
});

describe("reindex endpoint", () => {
  test("reindexKnowledgeBase POSTs the library-scoped rebuild path", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(202, { status: "enqueued" }));
    const result = await reindexKnowledgeBase("kb-1");

    expect(mockedFetch).toHaveBeenCalledWith(
      "http://gw/api/knowledge-bases/kb-1/reindex",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.status).toBe("enqueued");
  });

  test("getReindexStatus reads the status path and keeps the progress payload", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        in_progress: true,
        last_run: null,
        progress: { documents_total: 7, documents_done: 3, chunks_indexed: 42 },
      }),
    );

    const status = await getReindexStatus("kb-1");

    expect(mockedFetch).toHaveBeenCalledWith("http://gw/api/knowledge-bases/kb-1/reindex/status");
    expect(status.in_progress).toBe(true);
    expect(status.progress?.chunks_indexed).toBe(42);
  });
});
