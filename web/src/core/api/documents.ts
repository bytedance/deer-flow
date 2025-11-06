// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { resolveServiceURL } from "./resolve-service-url";

export interface DocumentInfo {
  id: string;
  name: string;
  size: number;
  hash: string;
  path: string;
  uploaded_at: string;
  metadata: Record<string, any>;
}

export interface UploadDocumentParams {
  file: File;
  onProgress?: (progress: number) => void;
}

export interface UploadDocumentResponse {
  success: boolean;
  document?: DocumentInfo;
  message?: string;
}

export async function uploadDocument({
  file,
  onProgress,
}: UploadDocumentParams): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.append("file", file);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    // 监听上传进度
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        const progress = Math.round((event.loaded / event.total) * 100);
        onProgress(progress);
      }
    });

    // 监听完成
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText);
          resolve({
            success: true,
            document: response.document,
            message: response.message,
          });
        } catch (error) {
          resolve({
            success: true,
            message: xhr.responseText,
          });
        }
      } else {
        try {
          const error = JSON.parse(xhr.responseText);
          const errorMessage = error.detail || error.message || "上传失败";
          reject(new Error(errorMessage));
        } catch {
          reject(new Error(`上传失败: ${xhr.statusText}`));
        }
      }
    });

    // 监听错误
    xhr.addEventListener("error", () => {
      reject(new Error("网络错误，请检查连接"));
    });

    // 监听中止
    xhr.addEventListener("abort", () => {
      reject(new Error("上传已取消"));
    });

    // 发送请求
    xhr.open("POST", resolveServiceURL("documents/upload"));
    xhr.send(formData);
  });
}

export interface DocumentListResponse {
  documents: DocumentInfo[];
  total: number;
}

export async function listDocuments(
  limit: number = 100,
  offset: number = 0,
): Promise<DocumentListResponse> {
  const response = await fetch(
    resolveServiceURL(`documents?limit=${limit}&offset=${offset}`),
  );
  if (!response.ok) {
    throw new Error("获取文档列表失败");
  }
  return response.json();
}

export async function getDocument(docId: string): Promise<DocumentInfo> {
  const response = await fetch(resolveServiceURL(`documents/${docId}`));
  if (!response.ok) {
    throw new Error("获取文档信息失败");
  }
  return response.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const response = await fetch(resolveServiceURL(`documents/${docId}`), {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error("删除文档失败");
  }
}







