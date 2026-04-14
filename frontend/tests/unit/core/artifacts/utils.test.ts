import { expect, test } from "vitest";

import {
  buildThreadFileTree,
  collectThreadFileTreeFolderIds,
  extractUploadVirtualPaths,
  getThreadFileDisplayPath,
  mergeThreadFilePaths,
  normalizeThreadHistoryFileKey,
} from "@/core/artifacts/utils";

test("extractUploadVirtualPaths includes upload and converted markdown paths once", () => {
  expect(
    extractUploadVirtualPaths([
      {
        filename: "report.pdf",
        size: 42,
        path: "/mnt/user-data/uploads/report.pdf",
        virtual_path: "/mnt/user-data/uploads/report.pdf",
        artifact_url: "/api/report.pdf",
        markdown_file: "report.md",
        markdown_path: "/mnt/user-data/uploads/report.md",
        markdown_virtual_path: "/mnt/user-data/uploads/report.md",
        markdown_artifact_url: "/api/report.md",
      },
      {
        filename: "report-copy.pdf",
        size: 42,
        path: "/mnt/user-data/uploads/report-copy.pdf",
        virtual_path: "/mnt/user-data/uploads/report.pdf",
        artifact_url: "/api/report-copy.pdf",
      },
    ]),
  ).toEqual([
    "/mnt/user-data/uploads/report.pdf",
    "/mnt/user-data/uploads/report.md",
  ]);
});

test("mergeThreadFilePaths preserves upload-first order and removes duplicates", () => {
  expect(
    mergeThreadFilePaths({
      uploads: [
        "/mnt/user-data/uploads/data.csv",
        "/mnt/user-data/uploads/data.md",
      ],
      artifacts: [
        "/mnt/user-data/uploads/data.md",
        "/mnt/user-data/outputs/report.md",
      ],
    }),
  ).toEqual([
    "/mnt/user-data/uploads/data.csv",
    "/mnt/user-data/uploads/data.md",
    "/mnt/user-data/outputs/report.md",
  ]);
});

test("getThreadFileDisplayPath trims the user-data prefix", () => {
  expect(getThreadFileDisplayPath("/mnt/user-data/outputs/report.md")).toBe(
    "outputs/report.md",
  );
});

test("normalizeThreadHistoryFileKey maps output files back to workspace history", () => {
  expect(
    normalizeThreadHistoryFileKey("/mnt/user-data/outputs/app/index.html"),
  ).toBe("workspace/app/index.html");
  expect(
    normalizeThreadHistoryFileKey("/mnt/user-data/uploads/report.md"),
  ).toBe("uploads/report.md");
});

test("buildThreadFileTree creates nested folder nodes in display path order", () => {
  const tree = buildThreadFileTree([
    "/mnt/user-data/outputs/app/index.html",
    "/mnt/user-data/outputs/app/css/style.css",
    "/mnt/user-data/uploads/brief.md",
  ]);

  expect(tree).toEqual([
    {
      id: "folder:outputs",
      kind: "folder",
      name: "outputs",
      path: "outputs",
      children: [
        {
          id: "folder:outputs/app",
          kind: "folder",
          name: "app",
          path: "outputs/app",
          children: [
            {
              id: "folder:outputs/app/css",
              kind: "folder",
              name: "css",
              path: "outputs/app/css",
              children: [
                {
                  id: "file:/mnt/user-data/outputs/app/css/style.css",
                  kind: "file",
                  name: "style.css",
                  path: "outputs/app/css/style.css",
                  filepath: "/mnt/user-data/outputs/app/css/style.css",
                  displayPath: "outputs/app/css/style.css",
                },
              ],
            },
            {
              id: "file:/mnt/user-data/outputs/app/index.html",
              kind: "file",
              name: "index.html",
              path: "outputs/app/index.html",
              filepath: "/mnt/user-data/outputs/app/index.html",
              displayPath: "outputs/app/index.html",
            },
          ],
        },
      ],
    },
    {
      id: "folder:uploads",
      kind: "folder",
      name: "uploads",
      path: "uploads",
      children: [
        {
          id: "file:/mnt/user-data/uploads/brief.md",
          kind: "file",
          name: "brief.md",
          path: "uploads/brief.md",
          filepath: "/mnt/user-data/uploads/brief.md",
          displayPath: "uploads/brief.md",
        },
      ],
    },
  ]);
  expect(collectThreadFileTreeFolderIds(tree)).toEqual([
    "folder:outputs",
    "folder:outputs/app",
    "folder:outputs/app/css",
    "folder:uploads",
  ]);
});
