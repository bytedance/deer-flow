/**
 * API functions for file uploads
 */

import { fetch, type WorkspaceRESTClient } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

export interface UploadRequestOptions {
  rest?: WorkspaceRESTClient;
  signal?: AbortSignal;
}

async function readUploadResponse<T>(
  response: Response,
  fallback: string,
  rest?: WorkspaceRESTClient,
): Promise<T> {
  const decode = async (response: Response): Promise<T> => {
    if (!response.ok)
      throw new Error(await readErrorDetail(response, fallback));
    return response.json();
  };
  return rest ? rest.consume(response, decode) : decode(response);
}

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
  options?: UploadRequestOptions,
): Promise<UploadResponse> {
  const formData = new FormData();

  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await (options?.rest?.fetch ?? fetch)(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads`,
    {
      method: "POST",
      body: formData,
      ...(options?.signal ? { signal: options.signal } : {}),
    },
  );

  return readUploadResponse(response, "Upload failed", options?.rest);
}

/**
 * Load the upload limits enforced by the gateway for a thread
 */
export async function getUploadLimits(
  threadId: string,
  options?: UploadRequestOptions,
): Promise<UploadLimits> {
  const response = await (options?.rest?.fetch ?? fetch)(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/limits`,
    ...(options?.signal ? ([{ signal: options.signal }] as const) : []),
  );

  return readUploadResponse(
    response,
    "Failed to load upload limits",
    options?.rest,
  );
}

/**
 * List all uploaded files for a thread
 */
export async function listUploadedFiles(
  threadId: string,
  options?: UploadRequestOptions,
): Promise<ListFilesResponse> {
  const response = await (options?.rest?.fetch ?? fetch)(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/list`,
    ...(options?.signal ? ([{ signal: options.signal }] as const) : []),
  );

  return readUploadResponse(
    response,
    "Failed to list uploaded files",
    options?.rest,
  );
}

/**
 * Delete an uploaded file
 */
export async function deleteUploadedFile(
  threadId: string,
  filename: string,
  options?: UploadRequestOptions,
): Promise<{ success: boolean; message: string }> {
  const encodedFilename = encodeURIComponent(filename);
  const response = await (options?.rest?.fetch ?? fetch)(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/${encodedFilename}`,
    {
      method: "DELETE",
      ...(options?.signal ? { signal: options.signal } : {}),
    },
  );

  return readUploadResponse(response, "Failed to delete file", options?.rest);
}
