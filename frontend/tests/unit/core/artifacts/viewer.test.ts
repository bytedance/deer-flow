import { describe, expect, test } from "@rstest/core";

import { urlOfArtifact } from "@/core/artifacts/utils";
import {
  ARTIFACT_VIEWER_ROUTE,
  artifactViewerTitle,
  parseArtifactViewerParams,
  parseArtifactViewerQuery,
  resolveArtifactOpenURL,
} from "@/core/artifacts/viewer";

const threadId = "7cfa5f8f-a2f8-47ad-acbd-da7137baf990";

function viewerParams(url: string) {
  expect(url.startsWith(`${ARTIFACT_VIEWER_ROUTE}?`)).toBe(true);
  return new URLSearchParams(url.slice(url.indexOf("?") + 1));
}

describe("resolveArtifactOpenURL", () => {
  test("routes markdown artifacts to the standalone viewer", () => {
    const filepath = "/mnt/user-data/outputs/report.md";

    const params = viewerParams(resolveArtifactOpenURL({ filepath, threadId }));

    expect(params.get("path")).toBe(filepath);
    expect(params.get("thread_id")).toBe(threadId);
    expect(params.get("mock")).toBe(null);
  });

  test("routes skill archives to the viewer because they render as markdown", () => {
    const filepath = "/mnt/user-data/outputs/my-helper.skill";

    const params = viewerParams(resolveArtifactOpenURL({ filepath, threadId }));

    expect(params.get("path")).toBe(filepath);
  });

  test("keeps html artifacts on the raw gateway URL so they stay downloads", () => {
    const filepath = "/mnt/user-data/outputs/page.html";

    expect(resolveArtifactOpenURL({ filepath, threadId })).toBe(
      urlOfArtifact({ filepath, threadId }),
    );
  });

  test("keeps non-markdown text artifacts on the raw gateway URL", () => {
    const filepath = "/mnt/user-data/outputs/notes.mdx";

    expect(resolveArtifactOpenURL({ filepath, threadId })).toBe(
      urlOfArtifact({ filepath, threadId }),
    );
  });

  test("keeps binary artifacts on the raw gateway URL", () => {
    const filepath = "/mnt/user-data/outputs/diagram.png";

    expect(resolveArtifactOpenURL({ filepath, threadId })).toBe(
      urlOfArtifact({ filepath, threadId }),
    );
  });

  test("carries the mock flag into the viewer URL", () => {
    const params = viewerParams(
      resolveArtifactOpenURL({
        filepath: "/mnt/user-data/outputs/report.md",
        threadId,
        isMock: true,
      }),
    );

    expect(params.get("mock")).toBe("true");
  });

  test("carries the mock flag into the raw URL for non-markdown artifacts", () => {
    const filepath = "/mnt/user-data/outputs/diagram.png";

    expect(resolveArtifactOpenURL({ filepath, threadId, isMock: true })).toBe(
      urlOfArtifact({ filepath, threadId, isMock: true }),
    );
  });
});

describe("parseArtifactViewerParams", () => {
  test("round-trips a URL built by resolveArtifactOpenURL", () => {
    const filepath = "/mnt/user-data/outputs/sub dir/rapport été.md";
    const url = resolveArtifactOpenURL({ filepath, threadId, isMock: true });

    expect(parseArtifactViewerParams(viewerParams(url))).toEqual({
      filepath,
      threadId,
      isMock: true,
    });
  });

  test("defaults the mock flag to false when absent", () => {
    const params = new URLSearchParams({
      path: "/mnt/user-data/outputs/report.md",
      thread_id: threadId,
    });

    expect(parseArtifactViewerParams(params)?.isMock).toBe(false);
  });

  test("returns null when the path is missing", () => {
    const params = new URLSearchParams({ thread_id: threadId });

    expect(parseArtifactViewerParams(params)).toBe(null);
  });

  test("returns null when the thread id is missing", () => {
    const params = new URLSearchParams({
      path: "/mnt/user-data/outputs/report.md",
    });

    expect(parseArtifactViewerParams(params)).toBe(null);
  });

  test("returns null when the path is blank", () => {
    const params = new URLSearchParams({ path: "  ", thread_id: threadId });

    expect(parseArtifactViewerParams(params)).toBe(null);
  });
});

describe("parseArtifactViewerQuery", () => {
  test("reads the Next.js searchParams record shape", () => {
    expect(
      parseArtifactViewerQuery({
        path: "/mnt/user-data/outputs/report.md",
        thread_id: threadId,
        mock: "true",
      }),
    ).toEqual({
      filepath: "/mnt/user-data/outputs/report.md",
      threadId,
      isMock: true,
    });
  });

  test("uses the first value when a parameter is repeated", () => {
    expect(
      parseArtifactViewerQuery({
        path: ["/mnt/user-data/outputs/first.md", "/etc/passwd"],
        thread_id: threadId,
      })?.filepath,
    ).toBe("/mnt/user-data/outputs/first.md");
  });

  test("returns null when the record carries no target", () => {
    expect(parseArtifactViewerQuery({})).toBe(null);
    expect(parseArtifactViewerQuery(undefined)).toBe(null);
  });
});

describe("artifactViewerTitle", () => {
  test("names the window after the artifact file", () => {
    expect(artifactViewerTitle("/mnt/user-data/outputs/report.md")).toBe(
      "report.md - DeerFlow",
    );
  });

  test("falls back to the product name without a target", () => {
    expect(artifactViewerTitle(undefined)).toBe("DeerFlow");
  });
});
