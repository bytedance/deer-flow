import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  createKnowledgeDataset,
  deleteKnowledgeDataset,
  deleteKnowledgeDocuments,
  listKnowledgeDatasets,
  listKnowledgeDocuments,
  parseKnowledgeDocuments,
  uploadKnowledgeDocuments,
} from "@/core/knowledge/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Bad Request" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("knowledge api", () => {
  test("lists datasets with parsing counters and unwraps the RAGFlow envelope", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        code: 0,
        data: [{ id: "dataset-1", name: "Policies", document_count: 2 }],
        total: 1,
      }),
    );

    await expect(listKnowledgeDatasets()).resolves.toEqual([
      { id: "dataset-1", name: "Policies", document_count: 2 },
    ]);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/knowledge/datasets?page=1&page_size=100&include_parsing_status=true",
    );
  });

  test("creates and admin-deletes a shared dataset", async () => {
    mockedFetch
      .mockResolvedValueOnce(
        jsonResponse(200, {
          code: 0,
          data: { id: "dataset-1", name: "Policies" },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(200, { code: 0, data: true }));

    await expect(
      createKnowledgeDataset({ name: "Policies", description: "Shared" }),
    ).resolves.toMatchObject({ id: "dataset-1", name: "Policies" });
    expect(mockedFetch).toHaveBeenNthCalledWith(
      1,
      "/backend/api/knowledge/datasets",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Policies", description: "Shared" }),
      },
    );

    await deleteKnowledgeDataset("dataset-1");
    expect(mockedFetch).toHaveBeenNthCalledWith(
      2,
      "/backend/api/knowledge/datasets/dataset-1",
      { method: "DELETE" },
    );
  });

  test("lists documents and reports the upstream total", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        code: 0,
        data: {
          docs: [{ id: "document-1", name: "handbook.pdf", run: "DONE" }],
          total: 1,
        },
      }),
    );

    await expect(
      listKnowledgeDocuments("dataset/with spaces"),
    ).resolves.toEqual({
      documents: [{ id: "document-1", name: "handbook.pdf", run: "DONE" }],
      total: 1,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/knowledge/datasets/dataset%2Fwith%20spaces/documents?page=1&page_size=100",
    );
  });

  test("uploads browser files as multipart without overriding the boundary", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        code: 0,
        data: [{ id: "document-1", name: "handbook.pdf" }],
      }),
    );
    const file = new File(["policy"], "handbook.pdf", {
      type: "application/pdf",
    });

    await expect(
      uploadKnowledgeDocuments("dataset-1", [file]),
    ).resolves.toMatchObject([{ id: "document-1" }]);
    const init = mockedFetch.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.headers).toBeUndefined();
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).getAll("file")).toEqual([file]);
  });

  test("starts parsing and admin-deletes only the selected documents", async () => {
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, { code: 0, data: true }))
      .mockResolvedValueOnce(jsonResponse(200, { code: 0, data: true }));

    await parseKnowledgeDocuments("dataset-1", ["document-1"]);
    expect(mockedFetch).toHaveBeenNthCalledWith(
      1,
      "/backend/api/knowledge/datasets/dataset-1/parse",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_ids: ["document-1"] }),
      },
    );

    await deleteKnowledgeDocuments("dataset-1", ["document-1"]);
    expect(mockedFetch).toHaveBeenNthCalledWith(
      2,
      "/backend/api/knowledge/datasets/dataset-1/documents",
      {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: ["document-1"] }),
      },
    );
  });

  test("uses the sanitized Gateway error detail", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(502, { detail: "Unable to connect to RAGFlow." }),
    );

    await expect(listKnowledgeDatasets()).rejects.toThrow(
      "Unable to connect to RAGFlow.",
    );
  });
});
