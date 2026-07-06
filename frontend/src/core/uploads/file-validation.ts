import type { UploadLimits } from "./api";

const MACOS_APP_BUNDLE_CONTENT_TYPES = new Set([
  "",
  "application/octet-stream",
]);

export const MACOS_APP_BUNDLE_UPLOAD_MESSAGE =
  "macOS .app bundles can't be uploaded directly from the browser. Compress the app as a .zip or upload the .dmg instead.";

export function isLikelyMacOSAppBundle(file: Pick<File, "name" | "type">) {
  return (
    file.name.toLowerCase().endsWith(".app") &&
    MACOS_APP_BUNDLE_CONTENT_TYPES.has(file.type)
  );
}

export function splitUnsupportedUploadFiles(fileList: File[] | FileList) {
  const incoming = Array.from(fileList);
  const accepted: File[] = [];
  const rejected: File[] = [];

  for (const file of incoming) {
    if (isLikelyMacOSAppBundle(file)) {
      rejected.push(file);
      continue;
    }
    accepted.push(file);
  }

  return {
    accepted,
    rejected,
    message: rejected.length > 0 ? MACOS_APP_BUNDLE_UPLOAD_MESSAGE : undefined,
  };
}

export type UploadLimitViolationCode =
  | "max_file_size"
  | "max_files"
  | "max_total_size";

export interface UploadLimitViolation {
  code: UploadLimitViolationCode;
  files: File[];
  limit: number;
}

export interface UploadLimitValidationResult {
  accepted: File[];
  rejected: File[];
  violations: UploadLimitViolation[];
}

/**
 * Validate files against the same per-request limits enforced by the gateway.
 * Existing files keep priority and incoming files are accepted in selection order.
 */
export function validateUploadLimits(
  existingFiles: File[],
  incomingFiles: File[] | FileList,
  limits?: UploadLimits,
): UploadLimitValidationResult {
  const incoming = Array.from(incomingFiles);
  if (!limits) {
    return { accepted: incoming, rejected: [], violations: [] };
  }

  let fileCount = existingFiles.length;
  let totalSize = existingFiles.reduce((total, file) => total + file.size, 0);
  const accepted: File[] = [];
  const rejectedByCode: Record<UploadLimitViolationCode, File[]> = {
    max_file_size: [],
    max_files: [],
    max_total_size: [],
  };

  for (const file of incoming) {
    if (file.size > limits.max_file_size) {
      rejectedByCode.max_file_size.push(file);
      continue;
    }
    if (fileCount >= limits.max_files) {
      rejectedByCode.max_files.push(file);
      continue;
    }
    if (totalSize + file.size > limits.max_total_size) {
      rejectedByCode.max_total_size.push(file);
      continue;
    }

    accepted.push(file);
    fileCount += 1;
    totalSize += file.size;
  }

  const limitByCode: Record<UploadLimitViolationCode, number> = {
    max_file_size: limits.max_file_size,
    max_files: limits.max_files,
    max_total_size: limits.max_total_size,
  };
  const codes: UploadLimitViolationCode[] = [
    "max_file_size",
    "max_files",
    "max_total_size",
  ];
  const violations = codes.flatMap((code) =>
    rejectedByCode[code].length > 0
      ? [{ code, files: rejectedByCode[code], limit: limitByCode[code] }]
      : [],
  );

  return {
    accepted,
    rejected: violations.flatMap((violation) => violation.files),
    violations,
  };
}

export function formatUploadSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Number((bytes / 1024).toFixed(1))} KiB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${Number((bytes / (1024 * 1024)).toFixed(1))} MiB`;
  }
  return `${Number((bytes / (1024 * 1024 * 1024)).toFixed(1))} GiB`;
}
