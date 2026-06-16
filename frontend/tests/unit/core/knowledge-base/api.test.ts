import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  KB_ALLOWED_EXTENSIONS,
  KB_UPLOAD_MAX_SIZE,
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
  validateUploadFile,
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

describe("upload validation constants", () => {
  test("KB_UPLOAD_MAX_SIZE matches backend _UPLOAD_MAX_SIZE", () => {
    expect(KB_UPLOAD_MAX_SIZE).toBe(20 * 1024 * 1024);
  });

  test("KB_ALLOWED_EXTENSIONS uses dot-prefixed lowercase values", () => {
    expect(KB_ALLOWED_EXTENSIONS).toEqual(
      new Set([".pdf", ".doc", ".docx", ".md", ".txt"]),
    );
  });

  test("KB_ALLOWED_EXTENSIONS is a Set for O(1) lookup", () => {
    expect(KB_ALLOWED_EXTENSIONS.has(".pdf")).toBe(true);
    expect(KB_ALLOWED_EXTENSIONS.has(".xlsx")).toBe(false);
    expect(KB_ALLOWED_EXTENSIONS.has("pdf")).toBe(false);
  });
});

describe("validateUploadFile", () => {
  test("returns null for a valid .pdf under 20 MB", () => {
    const file = new File(["x".repeat(100)], "report.pdf", {
      type: "application/pdf",
    });
    expect(validateUploadFile(file)).toBeNull();
  });

  test("returns null for a valid .md under 20 MB", () => {
    const file = new File(["x".repeat(100)], "README.md", { type: "text/markdown" });
    expect(validateUploadFile(file)).toBeNull();
  });

  test("returns unsupported_type for .xlsx", () => {
    const file = new File(["data"], "sheet.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    expect(validateUploadFile(file)).toBe("unsupported_type");
  });

  test("returns unsupported_type for file with no extension", () => {
    const file = new File(["text"], "README", { type: "text/plain" });
    expect(validateUploadFile(file)).toBe("unsupported_type");
  });

  test("returns too_large for file over 20 MB", () => {
    const file = new File(
      [new ArrayBuffer(21 * 1024 * 1024)],
      "large.pdf",
      { type: "application/pdf" },
    );
    expect(validateUploadFile(file)).toBe("too_large");
  });

  test("checks extension before size (unsupported_type wins over too_large)", () => {
    const file = new File(
      [new ArrayBuffer(21 * 1024 * 1024)],
      "large.xlsx",
      { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
    );
    expect(validateUploadFile(file)).toBe("unsupported_type");
  });

  test("handles uppercase extension", () => {
    const file = new File(["x".repeat(100)], "report.PDF", {
      type: "application/pdf",
    });
    expect(validateUploadFile(file)).toBeNull();
  });

  test("handles multi-dot filename", () => {
    const file = new File(["x".repeat(100)], "report.v2.pdf", {
      type: "application/pdf",
    });
    expect(validateUploadFile(file)).toBeNull();
  });
});
