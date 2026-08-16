import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { updateArtifactContent } from "@/core/artifacts/api";

afterEach(() => {
  rs.restoreAllMocks();
});

describe("updateArtifactContent", () => {
  it("sends the draft and expected revision to the opened artifact URL", async () => {
    const fetchMock = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          path: "/mnt/user-data/outputs/report.md",
          sha256: "b".repeat(64),
          size: 7,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await updateArtifactContent({
      threadId: "thread-1",
      filepath: "/mnt/user-data/outputs/report.md",
      content: "updated",
      expectedSha256: "a".repeat(64),
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(typeof url).toBe("string");
    expect(url as string).toContain(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/report.md",
    );
    expect(init?.method).toBe("PUT");
    expect(typeof init?.body).toBe("string");
    expect(JSON.parse(init?.body as string)).toEqual({
      content: "updated",
      expected_sha256: "a".repeat(64),
    });
  });

  it("preserves the response status for conflict handling", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Artifact changed" }), {
        status: 412,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      updateArtifactContent({
        threadId: "thread-1",
        filepath: "/mnt/user-data/outputs/report.md",
        content: "updated",
        expectedSha256: "a".repeat(64),
      }),
    ).rejects.toMatchObject({ status: 412 });
  });
});
