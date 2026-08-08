import { expect, test } from "@rstest/core";

import type { UploadedFileInfo } from "@/core/uploads/api";
import { uploadedFileInfoToMessageFile } from "@/core/uploads/message-files";

const BASE_INFO: UploadedFileInfo = {
  filename: "a.pdf",
  size: 42,
  path: "backend-path/a.pdf",
  virtual_path: "/mnt/user-data/uploads/a.pdf",
  artifact_url: "/api/artifacts/a.pdf",
};

test("preserves a collision-renamed Markdown companion", () => {
  expect(
    uploadedFileInfoToMessageFile({
      ...BASE_INFO,
      markdown_file: "a_1.md",
    }),
  ).toEqual({
    filename: "a.pdf",
    size: 42,
    path: "/mnt/user-data/uploads/a.pdf",
    status: "uploaded",
    markdown_file: "a_1.md",
  });
});

test("records explicit null when the upload has no Markdown companion", () => {
  expect(uploadedFileInfoToMessageFile(BASE_INFO)).toEqual({
    filename: "a.pdf",
    size: 42,
    path: "/mnt/user-data/uploads/a.pdf",
    status: "uploaded",
    markdown_file: null,
  });
});
