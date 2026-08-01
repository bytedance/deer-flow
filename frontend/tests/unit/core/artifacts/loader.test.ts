import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { loadArtifactContent } from "@/core/artifacts/loader";

afterEach(() => {
  rs.restoreAllMocks();
});

describe("loadArtifactContent", () => {
  it("uses the server content revision when available", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("content", {
        status: 200,
        headers: { ETag: `"${"a".repeat(64)}"` },
      }),
    );

    const loaded = await loadArtifactContent({
      filepath: "/mnt/user-data/outputs/report.md",
      threadId: "thread-1",
    });

    expect(loaded.sha256).toBe("a".repeat(64));
  });

  it("computes a revision for active text responses without a SHA-256 ETag", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("content", {
        status: 200,
        headers: { ETag: '"starlette-file-etag"' },
      }),
    );

    const loaded = await loadArtifactContent({
      filepath: "/mnt/user-data/outputs/page.html",
      threadId: "thread-1",
    });

    expect(loaded.sha256).toBe(
      "ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73",
    );
  });
});
