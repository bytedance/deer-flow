/**
 * API functions for file uploads
 */

import { apiFetch, apiJson } from "../api/fetch";

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

export async function uploadFiles(
  threadId: string,
  files: File[],
): Promise<UploadResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const res = await apiFetch(`/api/threads/${threadId}/uploads`, {
    method: "POST",
    body: formData,
    timeout: 120_000,
  });
  return res.json();
}

export async function listUploadedFiles(
  threadId: string,
): Promise<ListFilesResponse> {
  return apiJson<ListFilesResponse>(`/api/threads/${threadId}/uploads/list`);
}

export async function deleteUploadedFile(
  threadId: string,
  filename: string,
): Promise<{ success: boolean; message: string }> {
  return apiJson<{ success: boolean; message: string }>(
    `/api/threads/${threadId}/uploads/${filename}`,
    { method: "DELETE" },
  );
}
