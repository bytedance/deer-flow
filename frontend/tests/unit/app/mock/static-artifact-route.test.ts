import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { NextRequest } from "next/server";

import { GET } from "@/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route";

describe("static artifact mock route", () => {
  afterEach(() => {
    rs.restoreAllMocks();
  });

  it("streams only a manifest-owned public artifact", async () => {
    const fetchMock = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("artifact body", { status: 200 }));
    const request = new NextRequest(
      "http://deer-flow.test/mock/api/threads/thread/artifacts/file",
    );

    const response = await GET(request, {
      params: Promise.resolve({
        thread_id: "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
        artifact_path: ["mnt", "user-data", "outputs", "index.html"],
      }),
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://deer-flow.test/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/index.html",
      expect.objectContaining({ signal: request.signal }),
    );
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("artifact body");
  });

  it("preserves bounded range requests and partial-response metadata", async () => {
    const fetchMock = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("partial", {
        status: 206,
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Length": "7",
          "Content-Range": "bytes 0-6/2000000",
          "Content-Type": "text/plain",
        },
      }),
    );
    const request = new NextRequest(
      "http://deer-flow.test/mock/api/threads/thread/artifacts/file",
      { headers: { Range: "bytes=0-1048575" } },
    );

    const response = await GET(request, {
      params: Promise.resolve({
        thread_id: "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
        artifact_path: ["mnt", "user-data", "outputs", "index.html"],
      }),
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/demo/threads/"),
      expect.objectContaining({
        headers: expect.objectContaining({ Range: "bytes=0-1048575" }),
      }),
    );
    expect(response.status).toBe(206);
    expect(response.headers.get("Accept-Ranges")).toBe("bytes");
    expect(response.headers.get("Content-Range")).toBe("bytes 0-6/2000000");
  });

  it("rejects traversal before fetching", async () => {
    const fetchMock = rs.spyOn(globalThis, "fetch");
    const request = new NextRequest(
      "http://deer-flow.test/mock/api/threads/thread/artifacts/file",
    );

    const response = await GET(request, {
      params: Promise.resolve({
        thread_id: "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
        artifact_path: ["mnt", "user-data", "outputs", "..", "thread.json"],
      }),
    });

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
