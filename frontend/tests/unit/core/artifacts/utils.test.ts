import { expect, test } from "vitest";

import {
  extractUploadVirtualPaths,
  mergeThreadFilePaths,
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
