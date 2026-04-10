/**
 * API functions for file uploads
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

export interface UploadFilesOptions {
  onProgress?: (progress: number) => void;
}

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = await response.json().catch(() => ({ detail: fallback }));
  return error.detail ?? fallback;
}

/**
 * Upload files to a thread
 */
export async function uploadFiles(
  threadId: string,
  files: File[],
  options?: UploadFilesOptions,
): Promise<UploadResponse> {
  const formData = new FormData();

  files.forEach((file) => {
    formData.append("files", file);
  });

  return new Promise<UploadResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      `${getBackendBaseURL()}/api/threads/${threadId}/uploads`,
    );

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const progress = Math.min(
        100,
        Math.max(0, Math.round((event.loaded / event.total) * 100)),
      );
      options?.onProgress?.(progress);
    };

    xhr.onerror = () => {
      reject(new Error("Upload failed"));
    };

    xhr.onload = () => {
      const responseText = xhr.responseText || "";
      let payload: UploadResponse | { detail?: string } | undefined;
      try {
        payload = responseText
          ? (JSON.parse(responseText) as UploadResponse | { detail?: string })
          : undefined;
      } catch {
        payload = undefined;
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        const detail =
          payload && "detail" in payload ? payload.detail : undefined;
        reject(new Error(detail ?? "Upload failed"));
        return;
      }

      options?.onProgress?.(100);
      resolve(payload as UploadResponse);
    };

    xhr.send(formData);
  });
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
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/${filename}`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Failed to delete file"));
  }

  return response.json();
}
