import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type Dataset = {
  id: string;
  name: string;
  document_count: number;
  chunk_count: number;
};
export type KnowledgeDocument = {
  id: string;
  name: string;
  size: number;
  chunk_count: number;
  status: "pending" | "parsing" | "cancelled" | "ready" | "failed" | "unknown";
  progress: number;
};
export type DatasetList = {
  datasets: Dataset[];
  can_upload: boolean;
  can_create: boolean;
  max_file_bytes: number;
};
export type DocumentList = { documents: KnowledgeDocument[]; total: number };
export type UploadResult = {
  documents: KnowledgeDocument[];
  parsing_started: boolean;
};

export class KnowledgeError extends Error {
  constructor(public code: string) {
    super(code);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge-base${path}`,
    options,
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: { code?: string };
    } | null;
    throw new KnowledgeError(
      body?.detail?.code ??
        (response.status === 413
          ? "upload_too_large"
          : response.status === 403
            ? "knowledge_access_denied"
            : "request_failed"),
    );
  }
  return response.json() as Promise<T>;
}

export const fetchDatasets = () => request<DatasetList>("/datasets");
export const createDataset = (name: string) =>
  request<Dataset>("/datasets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
export const fetchDocuments = (id: string, page: number) =>
  request<DocumentList>(
    `/datasets/${encodeURIComponent(id)}/documents?page=${page}&page_size=20`,
  );
export function uploadDocument(id: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<UploadResult>(
    `/datasets/${encodeURIComponent(id)}/documents`,
    { method: "POST", body },
  );
}
export const parseDocument = (datasetId: string, documentId: string) =>
  request<{ parsing_started: boolean }>(
    `/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/parse`,
    { method: "POST" },
  );
