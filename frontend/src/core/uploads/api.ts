/**
 * API functions for file uploads
 */

import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

export interface UploadedFileInfo {
  filename: string;
  size: number;
  path: string;
  virtual_path: string;
  artifact_url: string;
  extension?: string;
  modified?: number;
  markdown_file?: string;
  markdown_path?: string;
  markdown_virtual_path?: string;
  markdown_artifact_url?: string;
}

export interface UploadResponse {
  success: boolean;
  files: UploadedFileInfo[];
  message: string;
  skipped_files: string[];
}

export interface ListFilesResponse {
  files: UploadedFileInfo[];
  count: number;
}

export interface UploadLimits {
  max_files: number;
  max_file_size: number;
  max_total_size: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatValidationIssue(issue: unknown): string | null {
  if (
    !isRecord(issue) ||
    typeof issue.msg !== "string" ||
    !Array.isArray(issue.loc)
  ) {
    return null;
  }

  if (issue.msg.trim().length === 0) {
    return null;
  }

  const location = issue.loc
    .filter(
      (part): part is string | number =>
        typeof part === "string" || typeof part === "number",
    )
    .map(String)
    .filter((part) => part.length > 0)
    .join(".");

  return location.length > 0 ? `${location}: ${issue.msg}` : issue.msg;
}

function serializeStructuredDetail(
  detail: Record<string, unknown> | unknown[],
): string | null {
  if (
    (Array.isArray(detail) && detail.length === 0) ||
    (!Array.isArray(detail) && Object.keys(detail).length === 0)
  ) {
    return null;
  }

  try {
    return JSON.stringify(detail);
  } catch {
    return null;
  }
}

function formatErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail.trim().length > 0 ? detail : null;
  }

  if (Array.isArray(detail)) {
    if (detail.length === 0) {
      return null;
    }

    const validationIssues = detail.map(formatValidationIssue);
    if (validationIssues.every((issue) => issue !== null)) {
      return validationIssues.join("; ");
    }

    return serializeStructuredDetail(detail);
  }

  if (isRecord(detail)) {
    return formatValidationIssue(detail) ?? serializeStructuredDetail(detail);
  }

  return null;
}

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = (await response.json().catch(() => null)) as unknown;
  if (!isRecord(error)) {
    return fallback;
  }

  return formatErrorDetail(error.detail) ?? fallback;
}

/**
 * Upload files to a thread
 */
export async function uploadFiles(
  threadId: string,
  files: File[],
): Promise<UploadResponse> {
  const formData = new FormData();

  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Upload failed"));
  }

  return response.json();
}

/**
 * Load the upload limits enforced by the gateway for a thread
 */
export async function getUploadLimits(threadId: string): Promise<UploadLimits> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/limits`,
  );

  if (!response.ok) {
    throw new Error(
      await readErrorDetail(response, "Failed to load upload limits"),
    );
  }

  return response.json();
}

/**
 * List all uploaded files for a thread
 */
export async function listUploadedFiles(
  threadId: string,
): Promise<ListFilesResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/list`,
  );

  if (!response.ok) {
    throw new Error(
      await readErrorDetail(response, "Failed to list uploaded files"),
    );
  }

  return response.json();
}

/**
 * Delete an uploaded file
 */
export async function deleteUploadedFile(
  threadId: string,
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const encodedFilename = encodeURIComponent(filename);
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/${encodedFilename}`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Failed to delete file"));
  }

  return response.json();
}
