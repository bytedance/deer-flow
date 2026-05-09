import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  createDocument,
  createKnowledgeBase,
  deleteDocument,
  deleteKnowledgeBase,
  listDocuments,
  listKnowledgeBases,
  reindexDocument,
  searchKnowledgeBase,
  updateDocument,
  updateKnowledgeBase,
} from "@/core/knowledge-base/api";

function mockResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  };
}

describe("knowledge-base API", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("document", { cookie: "csrf_token=test" });
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("listKnowledgeBases calls GET /api/knowledge-bases", async () => {
    const kbs = [{ id: "kb-1", name: "Test KB" }];
    fetchMock.mockResolvedValue(mockResponse(kbs));

    const result = await listKnowledgeBases();
    expect(result).toEqual(kbs);

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases");
  });

  test("createKnowledgeBase sends POST with body", async () => {
    const created = { id: "kb-new", name: "New KB" };
    fetchMock.mockResolvedValue(mockResponse(created));

    const result = await createKnowledgeBase({ name: "New KB" });
    expect(result).toEqual(created);

    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ name: "New KB" });
  });

  test("updateKnowledgeBase sends PATCH", async () => {
    const updated = { id: "kb-1", name: "Updated" };
    fetchMock.mockResolvedValue(mockResponse(updated));

    await updateKnowledgeBase("kb-1", { name: "Updated" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1");
    expect(init.method).toBe("PATCH");
  });

  test("deleteKnowledgeBase sends DELETE", async () => {
    fetchMock.mockResolvedValue(mockResponse(null));

    await deleteKnowledgeBase("kb-1");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1");
    expect(init.method).toBe("DELETE");
  });

  test("listDocuments calls GET with kb id", async () => {
    const docs = [{ id: "doc-1", title: "Doc" }];
    fetchMock.mockResolvedValue(mockResponse(docs));

    const result = await listDocuments("kb-1");
    expect(result).toEqual(docs);

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1/documents");
  });

  test("createDocument sends POST with title and content", async () => {
    const doc = { id: "doc-new", title: "New Doc" };
    fetchMock.mockResolvedValue(mockResponse(doc));

    await createDocument("kb-1", { title: "New Doc", content: "Hello" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1/documents");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ title: "New Doc", content: "Hello" });
  });

  test("updateDocument sends PATCH with docId", async () => {
    const doc = { id: "doc-1", title: "Updated" };
    fetchMock.mockResolvedValue(mockResponse(doc));

    await updateDocument("kb-1", "doc-1", { title: "Updated" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1/documents/doc-1");
    expect(init.method).toBe("PATCH");
  });

  test("deleteDocument sends DELETE", async () => {
    fetchMock.mockResolvedValue(mockResponse(null));

    await deleteDocument("kb-1", "doc-1");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1/documents/doc-1");
    expect(init.method).toBe("DELETE");
  });

  test("reindexDocument sends POST to reindex endpoint", async () => {
    fetchMock.mockResolvedValue(mockResponse(null));

    await reindexDocument("kb-1", "doc-1");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1/documents/doc-1/reindex");
    expect(init.method).toBe("POST");
  });

  test("searchKnowledgeBase sends POST with query and top_k", async () => {
    const searchResult = {
      results: [{ chunk_id: "c1", content: "text", score: 0.9, metadata: {} }],
      query: "test",
      knowledge_base_id: "kb-1",
    };
    fetchMock.mockResolvedValue(mockResponse(searchResult));

    const result = await searchKnowledgeBase("kb-1", "test", 3);
    expect(result).toEqual(searchResult);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/knowledge-bases/kb-1/search");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ query: "test", top_k: 3 });
  });

  test("throws on non-ok response with detail", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: () => Promise.resolve({ detail: "KB not found" }),
    });

    await expect(createKnowledgeBase({ name: "X" })).rejects.toThrow(
      "KB not found",
    );
  });

  test("throws generic message when no detail in error response", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.reject(new Error("parse error")),
    });

    await expect(listKnowledgeBases()).rejects.toThrow(
      "Failed to list knowledge bases",
    );
  });
});
