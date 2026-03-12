/**
 * API functions for file uploads
 *
 * Supports two upload strategies:
 * 1. Presigned URL (preferred): Browser uploads directly to R2 — fastest
 * 2. Multipart POST (fallback): Browser uploads through gateway server
 */

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
}

export interface ListFilesResponse {
  files: UploadedFileInfo[];
  count: number;
}

interface PresignedFile {
  url: string;
  key: string;
  virtual_path: string;
  artifact_url: string;
  markdown_file?: string;
  markdown_key?: string;
  markdown_virtual_path?: string;
  markdown_artifact_url?: string;
}

interface PresignBatchResponse {
  files: PresignedFile[];
}

/**
 * Upload files using presigned URLs (direct browser→R2).
 * Falls back to multipart POST if presigned URLs are unavailable.
 */
export async function uploadFiles(
  threadId: string,
  files: File[],
): Promise<UploadResponse> {
  // Try presigned URL upload first (fastest path)
  try {
    return await uploadFilesPresigned(threadId, files);
  } catch {
    // Fallback to multipart POST through gateway
    return await uploadFilesMultipart(threadId, files);
  }
}

/**
 * Upload via presigned URLs — browser uploads directly to R2.
 * Gateway is only called for URL generation (~50ms), not file transfer.
 */
async function uploadFilesPresigned(
  threadId: string,
  files: File[],
): Promise<UploadResponse> {
  const filenames = files.map((f) => f.name);
  const params = new URLSearchParams();
  filenames.forEach((fn) => params.append("filenames", fn));

  // 1. Get presigned URLs from gateway (fast, no file data transferred)
  const presignResponse = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/presign?${params.toString()}`,
    { method: "POST" },
  );

  if (!presignResponse.ok) {
    throw new Error("Presigned URLs not available");
  }

  const presignData: PresignBatchResponse = await presignResponse.json();

  // 2. Upload files directly to R2 in parallel
  const uploadPromises = files.map(async (file, i) => {
    const presigned = presignData.files[i];
    if (!presigned) throw new Error(`No presigned URL for ${file.name}`);

    const contentType =
      file.type || "application/octet-stream";

    const putResponse = await fetch(presigned.url, {
      method: "PUT",
      body: file,
      headers: {
        "Content-Type": contentType,
      },
    });

    if (!putResponse.ok) {
      throw new Error(`Direct upload failed for ${file.name}: ${putResponse.status}`);
    }

    return presigned;
  });

  const uploaded = await Promise.all(uploadPromises);

  // 3. Notify gateway to run background markdown conversion (fire-and-forget)
  const confirmParams = new URLSearchParams();
  filenames.forEach((fn) => confirmParams.append("filenames", fn));
  fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/confirm?${confirmParams.toString()}`,
    { method: "POST" },
  ).catch(() => {
    // Non-critical — markdown conversion can happen later
  });

  // 4. Build response matching UploadResponse format
  const uploadedFiles: UploadedFileInfo[] = uploaded.map((p, i) => {
    const file = files[i]!;
    const info: UploadedFileInfo = {
      filename: file.name,
      size: file.size,
      path: p.key,
      virtual_path: p.virtual_path,
      artifact_url: p.artifact_url,
    };
    if (p.markdown_file) {
      info.markdown_file = p.markdown_file;
      info.markdown_path = p.markdown_key;
      info.markdown_virtual_path = p.markdown_virtual_path;
      info.markdown_artifact_url = p.markdown_artifact_url;
    }
    return info;
  });

  return {
    success: true,
    files: uploadedFiles,
    message: `Successfully uploaded ${uploadedFiles.length} file(s)`,
  };
}

/**
 * Fallback: upload via multipart POST through gateway.
 * Used when R2 presigned URLs are not available (e.g., local storage).
 */
async function uploadFilesMultipart(
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
    const error = await response
      .json()
      .catch(() => ({ detail: "Upload failed" }));
    throw new Error(error.detail ?? "Upload failed");
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
    throw new Error("Failed to list uploaded files");
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
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/${filename}`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error("Failed to delete file");
  }

  return response.json();
}
