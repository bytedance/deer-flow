import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import { ARTIFACT_PREVIEW_MAX_BYTES } from "@/core/artifacts/loader";
import {
  attachProjectDocument,
  deleteProjectDocument,
  fetchProjectDocumentPreview,
  listProjectDocuments,
  listProjectThreadFiles,
  ProjectDocumentContentMissingError,
  promoteThreadFile,
  uploadProjectDocument,
} from "@/core/projects/api";

const mockedFetch = rs.mocked(fetcher);

const SAMPLE_DOCUMENT = {
  id: "doc-1",
  name: "q3-report.pdf",
  size_bytes: 1024,
  sha256: "abc123",
  content_missing: false,
  source_thread_id: null,
  source_kind: null,
  source_name: null,
  created_at: "2026-09-10T00:00:00+00:00",
  updated_at: "2026-09-10T00:00:00+00:00",
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = mockedFetch.mock.calls.at(-1) as [string, RequestInit];
  return { url, init };
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("project documents api", () => {
  it("lists documents with limit/offset query params", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        documents: [SAMPLE_DOCUMENT],
        total: 1,
        limit: 50,
        offset: 10,
      }),
    );

    const result = await listProjectDocuments("proj-1", {
      limit: 50,
      offset: 10,
    });

    const { url, init } = lastCall();
    expect(url).toBe(
      "/backend/api/projects/proj-1/documents?limit=50&offset=10",
    );
    expect(init.method).toBe("GET");
    expect(result.total).toBe(1);
    expect(result.documents[0]?.id).toBe("doc-1");
  });

  it("lists documents without query params when none given", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { documents: [], total: 0, limit: 100, offset: 0 }),
    );

    await listProjectDocuments("proj-1");

    expect(lastCall().url).toBe("/backend/api/projects/proj-1/documents");
  });

  it("encodes the project id in document URLs", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { documents: [], total: 0, limit: 100, offset: 0 }),
    );

    await listProjectDocuments("proj/ect 1");

    expect(lastCall().url).toBe(
      "/backend/api/projects/proj%2Fect%201/documents",
    );
  });

  it("uploads exactly one multipart file plus an optional name", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(201, { document: SAMPLE_DOCUMENT, deduplicated: false }),
    );
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    const result = await uploadProjectDocument("proj-1", {
      file,
      name: "renamed.txt",
    });

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/projects/proj-1/documents");
    expect(init.method).toBe("POST");
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect((body.get("file") as File).name).toBe("notes.txt");
    expect(body.get("name")).toBe("renamed.txt");
    // JSON content type must not be set; the browser sets the multipart boundary.
    expect(
      (init.headers as Record<string, string> | undefined)?.["Content-Type"],
    ).toBeUndefined();
    expect(result.deduplicated).toBe(false);
  });

  it("omits the name field when not provided", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { document: SAMPLE_DOCUMENT, deduplicated: true }),
    );
    const file = new File(["hello"], "notes.txt");

    const result = await uploadProjectDocument("proj-1", { file });

    const body = lastCall().init.body as FormData;
    expect(body.get("name")).toBeNull();
    // A 200 dedup hit is success, not an error.
    expect(result.deduplicated).toBe(true);
  });

  it("promotes a thread file with the frozen from-thread body", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(201, { document: SAMPLE_DOCUMENT, deduplicated: false }),
    );

    await promoteThreadFile("proj-1", {
      thread_id: "thread-1",
      kind: "output",
      name: "report.md",
      shelf_name: "Q3 report.md",
    });

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/projects/proj-1/documents/from-thread");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      thread_id: "thread-1",
      kind: "output",
      name: "report.md",
      shelf_name: "Q3 report.md",
    });
  });

  it("omits shelf_name from the from-thread body when undefined", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { document: SAMPLE_DOCUMENT, deduplicated: true }),
    );

    await promoteThreadFile("proj-1", {
      thread_id: "thread-1",
      kind: "upload",
      name: "input.csv",
    });

    expect(JSON.parse(lastCall().init.body as string)).toEqual({
      thread_id: "thread-1",
      kind: "upload",
      name: "input.csv",
    });
  });

  it("attaches a document to a thread and returns the upload descriptor", async () => {
    const attached = {
      filename: "q3-report.pdf",
      size_bytes: 1024,
      virtual_path: "/mnt/user-data/uploads/q3-report.pdf",
      artifact_url:
        "/api/threads/thread-1/artifacts/mnt/user-data/uploads/q3-report.pdf",
    };
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, attached));

    const result = await attachProjectDocument("proj-1", "doc 1", "thread/1");

    const { url, init } = lastCall();
    expect(url).toBe(
      "/backend/api/projects/proj-1/documents/doc%201/attach-to-thread/thread%2F1",
    );
    expect(init.method).toBe("POST");
    expect(result).toEqual(attached);
  });

  it("deletes a document with an encoded path", async () => {
    mockedFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await deleteProjectDocument("proj-1", "doc 1");

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/projects/proj-1/documents/doc%201");
    expect(init.method).toBe("DELETE");
  });

  it("lists thread files with cursor and limit params", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { groups: [], next_offset: null, truncated: false }),
    );

    const result = await listProjectThreadFiles("proj-1", {
      offset: 20,
      thread_limit: 10,
      file_limit: 25,
    });

    const { url, init } = lastCall();
    expect(url).toBe(
      "/backend/api/projects/proj-1/thread-files?offset=20&thread_limit=10&file_limit=25",
    );
    expect(init.method).toBe("GET");
    expect(result.next_offset).toBeNull();
  });

  it("surfaces the server error detail", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(404, { detail: "Project document not found" }),
    );

    await expect(deleteProjectDocument("proj-1", "doc-x")).rejects.toThrow(
      "Project document not found",
    );
  });

  it("falls back to a generic message for non-JSON errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("gateway down", { status: 502 }),
    );

    await expect(listProjectDocuments("proj-1")).rejects.toThrow(
      "Failed to load project documents.",
    );
  });
});

describe("fetchProjectDocumentPreview", () => {
  it("requests a bounded byte range and marks a 206 text prefix truncated", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("# partial", {
        status: 206,
        headers: {
          "Content-Type": "text/markdown; charset=utf-8",
          "Content-Range": `bytes 0-${ARTIFACT_PREVIEW_MAX_BYTES - 1}/${ARTIFACT_PREVIEW_MAX_BYTES * 50}`,
        },
      }),
    );

    const preview = await fetchProjectDocumentPreview("proj-1", "doc-1");

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/projects/proj-1/documents/doc-1/content");
    expect((init.headers as Record<string, string>).Range).toBe(
      `bytes=0-${ARTIFACT_PREVIEW_MAX_BYTES - 1}`,
    );
    expect(preview).toEqual({
      kind: "text",
      content: "# partial",
      truncated: true,
      previewBytes: 9,
      totalBytes: ARTIFACT_PREVIEW_MAX_BYTES * 50,
    });
  });

  it("marks an untruncated 200 with an oversized Content-Length truncated", async () => {
    // The content endpoint normally honors Range (Starlette FileResponse);
    // if a proxy strips it, the advertised length still forces the
    // truncation UI instead of rendering a prefix as the whole file.
    mockedFetch.mockResolvedValueOnce(
      new Response("plain body", {
        status: 200,
        headers: {
          "Content-Type": "text/plain",
          "Content-Length": String(ARTIFACT_PREVIEW_MAX_BYTES * 50),
        },
      }),
    );

    const preview = await fetchProjectDocumentPreview("proj-1", "doc-1");

    expect((lastCall().init.headers as Record<string, string>).Range).toBe(
      `bytes=0-${ARTIFACT_PREVIEW_MAX_BYTES - 1}`,
    );
    expect(preview.kind).toBe("text");
    expect(preview.kind === "text" && preview.truncated).toBe(true);
  });

  it("returns a small 200 text document whole", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("hello", {
        status: 200,
        headers: {
          "Content-Type": "text/plain",
          "Content-Length": "5",
        },
      }),
    );

    const preview = await fetchProjectDocumentPreview("proj-1", "doc-1");

    expect(preview).toEqual({
      kind: "text",
      content: "hello",
      truncated: false,
      previewBytes: 5,
      totalBytes: 5,
    });
  });

  it("routes a PDF to its own preview kind without decoding it", async () => {
    const response = new Response("%PDF-1.7 binary", {
      status: 200,
      headers: { "Content-Type": "application/pdf" },
    });
    const textSpy = rs.spyOn(response, "text");
    const arrayBufferSpy = rs.spyOn(response, "arrayBuffer");
    mockedFetch.mockResolvedValueOnce(response);

    const preview = await fetchProjectDocumentPreview("proj-1", "doc-1");

    expect(preview).toEqual({ kind: "pdf" });
    expect(textSpy).not.toHaveBeenCalled();
    expect(arrayBufferSpy).not.toHaveBeenCalled();
  });

  it("returns the unsupported fallback for non-viewable binary content", async () => {
    const response = new Response("PK zip bytes", {
      status: 200,
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    });
    const textSpy = rs.spyOn(response, "text");
    mockedFetch.mockResolvedValueOnce(response);

    const preview = await fetchProjectDocumentPreview("proj-1", "doc-1");

    expect(preview).toEqual({ kind: "unsupported" });
    expect(textSpy).not.toHaveBeenCalled();
  });

  it.each(["image/svg+xml", "application/xhtml+xml", "application/rss+xml"])(
    "keeps active content (%s) out of the iframe branch",
    async (contentType) => {
      // The endpoint serves the XML family as an attachment; the sandboxed
      // iframe would block that download and render a blank frame, so these
      // must land in the unsupported fallback with its download action.
      // (``text/*`` members of the family — html/xml/xsl — take the safe
      // text-decode branch instead, exactly like artifact text previews.)
      const response = new Response("<svg xmlns='x'><script/></svg>", {
        status: 200,
        headers: { "Content-Type": contentType },
      });
      const textSpy = rs.spyOn(response, "text");
      mockedFetch.mockResolvedValueOnce(response);

      const preview = await fetchProjectDocumentPreview("proj-1", "doc-1");

      expect(preview).toEqual({ kind: "unsupported" });
      expect(textSpy).not.toHaveBeenCalled();
    },
  );
  it.each(["image/png", "video/mp4", "audio/mpeg"])(
    "keeps passive binaries (%s) on the iframe branch",
    async (contentType) => {
      mockedFetch.mockResolvedValueOnce(
        new Response("binary", {
          status: 200,
          headers: { "Content-Type": contentType },
        }),
      );

      const preview = await fetchProjectDocumentPreview("proj-1", "doc-1");

      expect(preview).toEqual({ kind: "binary" });
    },
  );

  it("throws the content-missing error on a 409", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(409, { detail: { code: "content_missing" } }),
    );

    await expect(
      fetchProjectDocumentPreview("proj-1", "doc-1"),
    ).rejects.toBeInstanceOf(ProjectDocumentContentMissingError);
  });
});
