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
