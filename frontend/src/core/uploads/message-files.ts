import type { FileInMessage } from "../messages/utils";

import type { UploadedFileInfo } from "./api";

export function uploadedFileInfoToMessageFile(
  info: UploadedFileInfo,
): FileInMessage {
  return {
    filename: info.filename,
    size: info.size,
    path: info.virtual_path,
    status: "uploaded",
    markdown_file: info.markdown_file ?? null,
  };
}
