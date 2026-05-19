/**
 * API functions for file uploads
 */

import { fetchGateway } from "../api";
import { getBackendBaseURL } from "../config";

import {
  ConversionError,
  type ConversionErrorBody,
} from "./conversion-errors";

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
}

export interface ListFilesResponse {
  files: UploadedFileInfo[];
  count: number;
}

/**
 * Read a FastAPI error response. Conversion failures (Sprint C.1.2) carry
 * a structured `{code, message, filename}` detail body so callers can
 * branch on the stable `code` enum. Any other shape falls back to the
 * legacy string `detail`.
 */
async function consumeErrorBody(
  response: Response,
  fallback: string,
): Promise<{ conversion?: ConversionErrorBody; message: string }> {
  const body = (await response.json().catch(() => null)) as
    | { detail?: ConversionErrorBody | string }
    | null;
  const detail = body?.detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    return {
      conversion: detail,
      message: detail.message ?? fallback,
    };
  }
  return {
    message: typeof detail === "string" ? detail : fallback,
  };
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

  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!response.ok) {
    const { conversion, message } = await consumeErrorBody(
      response,
      "Upload failed",
    );
    if (conversion) {
      throw new ConversionError(conversion);
    }
    throw new Error(message);
  }

  return response.json();
}

/**
 * List all uploaded files for a thread
 */
export async function listUploadedFiles(
  threadId: string,
): Promise<ListFilesResponse> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/list`,
  );

  if (!response.ok) {
    const { message } = await consumeErrorBody(
      response,
      "Failed to list uploaded files",
    );
    throw new Error(message);
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
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/${filename}`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    const { message } = await consumeErrorBody(
      response,
      "Failed to delete file",
    );
    throw new Error(message);
  }

  return response.json();
}
