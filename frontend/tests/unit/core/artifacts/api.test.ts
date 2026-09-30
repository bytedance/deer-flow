import { afterEach, describe, expect, it, rs } from "@rstest/core";

import {
  downloadArtifactArchive,
  getArtifactArchiveManifest,
  updateArtifactContent,
} from "@/core/artifacts/api";

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

describe("downloadArtifactArchive", () => {
  it("posts to the encoded run endpoint and preserves the server filename", async () => {
    const blob = new Blob(["zip"]);
    const fetchMock = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(blob, {
        headers: {
          "Content-Disposition": 'attachment; filename="artifacts-run-1.zip"',
        },
      }),
    );

    const result = await downloadArtifactArchive({
      threadId: "thread #1",
      runId: "run/1",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/thread%20%231/runs/run%2F1/artifacts/archive",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(result.filename).toBe("artifacts-run-1.zip");
    expect(await result.blob.text()).toBe("zip");
  });
});

describe("getArtifactArchiveManifest", () => {
  it("reads the verified delivery count from the encoded run endpoint", async () => {
    const fetchMock = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ file_count: 3 }), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await getArtifactArchiveManifest({
      threadId: "thread #1",
      runId: "run/1",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/thread%20%231/runs/run%2F1/artifacts/archive",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result).toEqual({ fileCount: 3 });
  });
});
