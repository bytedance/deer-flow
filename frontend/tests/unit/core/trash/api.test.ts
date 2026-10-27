import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  emptyTrash,
  listTrashDocuments,
  purgeTrashDocument,
  RestoreConflictError,
  restoreTrashDocument,
} from "@/core/trash/api";

const mockedFetch = rs.mocked(fetcher);

const SAMPLE_TRASH_DOCUMENT = {
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
  trashed_at: "2026-09-12T00:00:00+00:00",
  trash_origin: { project_id: "proj-1", project_name: "Roadmap" },
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

describe("trash api", () => {
  it("lists trashed documents with limit/offset query params", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        documents: [SAMPLE_TRASH_DOCUMENT],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    );

    const result = await listTrashDocuments({ limit: 50, offset: 0 });

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/trash/documents?limit=50&offset=0");
    expect(init.method).toBe("GET");
    expect(result.documents[0]?.trash_origin?.project_name).toBe("Roadmap");
  });

  it("restores with an empty body when no target project is given", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        outcome: "restored",
        document: SAMPLE_TRASH_DOCUMENT,
      }),
    );

    const result = await restoreTrashDocument("doc-1");

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/trash/documents/doc-1/restore");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({});
    expect(result.outcome).toBe("restored");
  });

  it("restores with a project_id body when a target is given", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { outcome: "merged", document: SAMPLE_TRASH_DOCUMENT }),
    );

    const result = await restoreTrashDocument("doc 1", {
      projectId: "proj-2",
    });

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/trash/documents/doc%201/restore");
    expect(JSON.parse(init.body as string)).toEqual({ project_id: "proj-2" });
    expect(result.outcome).toBe("merged");
  });

  it("surfaces a 409 content_missing as RestoreConflictError", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(409, { detail: "content_missing" }),
    );

    let thrown: unknown;
    try {
      await restoreTrashDocument("doc-1");
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(RestoreConflictError);
    expect((thrown as RestoreConflictError).detail).toBe("content_missing");
    expect((thrown as RestoreConflictError).message).toBe("content_missing");
  });

  it("throws a plain error for other restore failures", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(404, { detail: "Document not found" }),
    );

    let thrown: unknown;
    try {
      await restoreTrashDocument("doc-1");
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(Error);
    expect(thrown).not.toBeInstanceOf(RestoreConflictError);
    expect((thrown as Error).message).toBe("Document not found");
  });

  it("purges one document with a POST to its purge route", async () => {
    mockedFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await purgeTrashDocument("doc 1");

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/trash/documents/doc%201/purge");
    expect(init.method).toBe("POST");
  });

  it("empties the trash and returns the purged count", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { purged: 3 }));

    const result = await emptyTrash();

    const { url, init } = lastCall();
    expect(url).toBe("/backend/api/trash/purge");
    expect(init.method).toBe("POST");
    expect(result.purged).toBe(3);
  });

  it("surfaces the server error detail on list failures", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(503, { detail: "Projects unavailable" }),
    );

    await expect(listTrashDocuments()).rejects.toThrow("Projects unavailable");
  });
});
