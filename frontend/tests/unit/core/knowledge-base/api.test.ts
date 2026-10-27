import { afterEach, describe, expect, it, rs } from "@rstest/core";

import {
  fetchDocuments,
  KnowledgeError,
  uploadDocument,
} from "@/core/knowledge-base/api";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
afterEach(() => {
  mocks.fetch.mockReset();
});

describe("knowledge API", () => {
  it("sends multipart bytes through the authenticated fetcher without overriding its boundary", async () => {
    mocks.fetch.mockResolvedValue(
      new Response(JSON.stringify({ documents: [], parsing_started: true })),
    );
    const file = new File(["hello"], "notes.txt");
    await uploadDocument("dataset", file);
    const [url, options] = mocks.fetch.mock.calls[0]!;
    expect(url).toBe("/api/knowledge-base/datasets/dataset/documents");
    expect(options.method).toBe("POST");
    expect(options.headers).toBeUndefined();
    expect((options.body as FormData).get("file")).toBe(file);
  });
  it("encodes identifiers and preserves pagination", async () => {
    mocks.fetch.mockResolvedValue(new Response('{"documents":[],"total":0}'));
    await fetchDocuments("a/b", 3);
    expect(mocks.fetch.mock.calls[0]![0]).toBe(
      "/api/knowledge-base/datasets/a%2Fb/documents?page=3&page_size=20",
    );
  });
  it("handles proxy 413 responses without JSON", async () => {
    mocks.fetch.mockResolvedValue(new Response("too large", { status: 413 }));
    await expect(fetchDocuments("dataset", 1)).rejects.toEqual(
      new KnowledgeError("upload_too_large"),
    );
  });
});
