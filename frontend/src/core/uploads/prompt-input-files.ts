import type { FileUIPart } from "ai";

export type PromptInputFilePart = FileUIPart & {
  // Transient submit-time handle to the original browser File; not serializable.
  file?: File;
};

export async function promptInputFilePartToFile(
  filePart: PromptInputFilePart,
): Promise<File | null> {
  if (filePart.file instanceof File) {
    const filename =
      typeof filePart.filename === "string" && filePart.filename.length > 0
        ? filePart.filename
        : filePart.file.name;
    const mediaType =
      typeof filePart.mediaType === "string" && filePart.mediaType.length > 0
        ? filePart.mediaType
        : filePart.file.type;

    if (filePart.file.name === filename && filePart.file.type === mediaType) {
      return filePart.file;
    }

    return new File([filePart.file], filename, { type: mediaType });
  }

  if (!filePart.url || !filePart.filename) {
    return null;
  }

  try {
    const response = await fetch(filePart.url);
    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status} while fetching fallback file URL`,
      );
    }
    const blob = await response.blob();

    return new File([blob], filePart.filename, {
      type: filePart.mediaType || blob.type,
    });
  } catch (error) {
    console.warn("promptInputFilePartToFile: fetch fallback failed", {
      error,
      url: filePart.url,
      filename: filePart.filename,
    });
    return null;
  }
}
