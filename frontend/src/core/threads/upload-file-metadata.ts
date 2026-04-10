import type { FileInMessage } from "../messages/utils";
import type { UploadedFileInfo } from "../uploads/api";

export function buildMessageFilesFromUploadInfo(
  uploadedFiles: UploadedFileInfo[],
): FileInMessage[] {
  return uploadedFiles.map((info) => {
    const file: FileInMessage = {
      filename: info.filename,
      size:
        typeof info.size === "string"
          ? Number.parseInt(info.size, 10)
          : info.size,
      path: info.virtual_path,
      status: "uploaded",
    };

    if (info.markdown_file && info.markdown_virtual_path) {
      file.markdown_file = info.markdown_file;
      file.markdown_path = info.markdown_virtual_path;
    }

    if (info.extracted_images?.length) {
      file.extracted_images = info.extracted_images.map((image) => ({
        ...image,
        size:
          typeof image.size === "string"
            ? Number.parseInt(image.size, 10)
            : image.size,
        path: image.virtual_path,
      }));
    }

    return file;
  });
}
