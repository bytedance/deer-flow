import type { FileInMessage } from "@/core/messages/utils";

import type { UploadedFileInfo } from "./api";

export function isSafeMarkdownCompanion(
  name: string | undefined,
): name is string {
  return (
    typeof name === "string" &&
    name.endsWith(".md") &&
    name !== ".md" &&
    !name.includes("/") &&
    !name.includes("\\") &&
    !name.includes("\0")
  );
}

export function toSubmittedMessageFiles(
  files: UploadedFileInfo[],
): FileInMessage[] {
  return files.map((info) => ({
    filename: info.filename,
    size: info.size,
    path: info.virtual_path,
    status: "uploaded" as const,
    ...(isSafeMarkdownCompanion(info.markdown_file)
      ? { markdown_file: info.markdown_file }
      : {}),
  }));
}
