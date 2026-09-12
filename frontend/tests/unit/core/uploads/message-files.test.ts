import { expect, test } from "@rstest/core";

import type { UploadedFileInfo } from "@/core/uploads/api";
import {
  isSafeMarkdownCompanion,
  toSubmittedMessageFiles,
} from "@/core/uploads/message-files";

const pdf: UploadedFileInfo = {
  filename: "report.pdf",
  size: 12,
  path: "/host/report.pdf",
  virtual_path: "/mnt/user-data/uploads/report.pdf",
  artifact_url: "/api/threads/t/artifacts/mnt/user-data/uploads/report.pdf",
  markdown_file: "report.md",
  markdown_virtual_path: "/mnt/user-data/uploads/report.md",
};

test("forwards a same-directory markdown companion onto the submitted file", () => {
  expect(toSubmittedMessageFiles([pdf])).toEqual([
    {
      filename: "report.pdf",
      size: 12,
      path: "/mnt/user-data/uploads/report.pdf",
      status: "uploaded",
      markdown_file: "report.md",
    },
  ]);
});

test("forwards collision-renamed companions such as a_1.md", () => {
  const files = toSubmittedMessageFiles([
    {
      ...pdf,
      filename: "a.pdf",
      virtual_path: "/mnt/user-data/uploads/a.pdf",
      artifact_url: "/api/threads/t/artifacts/mnt/user-data/uploads/a.pdf",
      markdown_file: "a_1.md",
    },
  ]);
  expect(files[0]?.markdown_file).toBe("a_1.md");
});

test("drops traversal and non-markdown companion names", () => {
  expect(isSafeMarkdownCompanion("../escape.md")).toBe(false);
  expect(isSafeMarkdownCompanion("notes.txt")).toBe(false);
  expect(
    toSubmittedMessageFiles([{ ...pdf, markdown_file: "../escape.md" }])[0]
      ?.markdown_file,
  ).toBeUndefined();
});
