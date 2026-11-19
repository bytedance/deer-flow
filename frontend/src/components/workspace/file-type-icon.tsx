import { getFileExtension, getFileIcon } from "@/core/utils/files";
import { cn } from "@/lib/utils";

/** File-format colors are identification cues, shared by uploads and outputs. */
export function FileTypeIcon({
  filename,
  className,
  compact = false,
}: {
  filename: string;
  className?: string;
  compact?: boolean;
}) {
  const extension = getFileExtension(filename);
  const kind = ["xls", "xlsx", "csv", "tsv"].includes(extension)
    ? "sheet"
    : ["doc", "docx"].includes(extension)
      ? "document"
      : ["ppt", "pptx"].includes(extension)
        ? "slides"
        : ["json", "jsonc", "json5"].includes(extension)
          ? "data"
          : "file";
  return (
    <span
      aria-hidden="true"
      data-file-kind={kind}
      className={cn(
        "file-type-icon inline-flex shrink-0 items-center justify-center rounded-xl",
        compact ? "size-6 rounded-md" : "size-11",
        className,
      )}
    >
      {getFileIcon(filename, compact ? "size-4" : "size-6")}
    </span>
  );
}
