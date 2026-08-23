import type { KnowledgeDataset } from "./types";

export type DatasetParsingKind = "empty" | "parsing" | "ready" | "failed";

export type DatasetParsingState = {
  kind: DatasetParsingKind;
  completed: number;
  total: number;
  percent: number;
};

function safeCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : 0;
}

export function datasetParsingState(
  dataset: KnowledgeDataset,
): DatasetParsingState {
  const unstart = safeCount(dataset.unstart_count);
  const running = safeCount(dataset.running_count);
  const cancelled = safeCount(dataset.cancel_count);
  const done = safeCount(dataset.done_count);
  const failed = safeCount(dataset.fail_count);
  const counterTotal = unstart + running + cancelled + done + failed;
  const total = Math.max(counterTotal, safeCount(dataset.document_count));
  const completed = Math.min(done, total);
  const percent = total === 0 ? 0 : Math.round((completed / total) * 100);

  if (unstart > 0 || running > 0) {
    return { kind: "parsing", completed, total, percent };
  }
  if (failed > 0) {
    return { kind: "failed", completed, total, percent };
  }
  if (total === 0) {
    return { kind: "empty", completed: 0, total: 0, percent: 0 };
  }
  return { kind: "ready", completed, total, percent: 100 };
}

export type DocumentRunKind =
  | "unparsed"
  | "parsing"
  | "ready"
  | "failed"
  | "cancelled";

export function documentRunKind(run: string | undefined): DocumentRunKind {
  switch (run?.toUpperCase()) {
    case "RUNNING":
      return "parsing";
    case "DONE":
      return "ready";
    case "FAIL":
      return "failed";
    case "CANCEL":
      return "cancelled";
    default:
      return "unparsed";
  }
}

export type KnowledgeUploadError =
  | "no_files"
  | "too_many_files"
  | "file_too_large"
  | "request_too_large";

const MAX_FILES = 10;
const MAX_FILE_BYTES = 50 * 1024 * 1024;
const MAX_REQUEST_BYTES = 100 * 1024 * 1024;

export function validateKnowledgeUpload(
  files: readonly File[],
): KnowledgeUploadError | null {
  if (files.length === 0) return "no_files";
  if (files.length > MAX_FILES) return "too_many_files";
  if (files.some((file) => file.size > MAX_FILE_BYTES)) {
    return "file_too_large";
  }
  if (files.reduce((total, file) => total + file.size, 0) > MAX_REQUEST_BYTES) {
    return "request_too_large";
  }
  return null;
}

export function formatKnowledgeFileSize(bytes: number | undefined): string {
  const value = safeCount(bytes);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
