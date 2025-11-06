import type { Resource } from "../messages";

import { resolveServiceURL } from "./resolve-service-url";

export function queryRAGResources(query: string) {
  return fetch(resolveServiceURL(`rag/resources?query=${query}`), {
    method: "GET",
  })
    .then((res) => res.json())
    .then((res) => {
      return res.resources as Array<Resource>;
    })
    .catch(() => {
      return [];
    });
}

export interface UploadDocumentParams {
  file: File;
  datasetName?: string;
  datasetId?: string;
  onProgress?: (progress: number) => void;
}

export interface UploadDocumentResponse {
  success: boolean;
  resource?: Resource;
  message?: string;
}

export async function uploadDocument({
  file,
  datasetName,
  datasetId,
  onProgress,
}: UploadDocumentParams): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.append("file", file);

  if (datasetName) {
    formData.append("dataset_name", datasetName);
  }

  if (datasetId) {
    formData.append("dataset_id", datasetId);
  }

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
            resource: response.resource,
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
    xhr.open("POST", resolveServiceURL("rag/upload"));
    xhr.send(formData);
  });
}