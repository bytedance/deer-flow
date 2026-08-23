import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  CreateKnowledgeDatasetRequest,
  KnowledgeDataset,
  KnowledgeDocument,
  KnowledgeDocumentPage,
} from "./types";

type RAGFlowEnvelope<T> = {
  code: number;
  data: T;
};

function knowledgeUrl(path: string): string {
  return `${getBackendBaseURL()}/api/knowledge${path}`;
}

async function readEnvelope<T>(
  response: Response,
  fallback: string,
): Promise<T> {
  if (!response.ok) {
    await throwGatewayApiError(response, fallback);
  }
  const envelope = (await response.json()) as RAGFlowEnvelope<T>;
  return envelope.data;
}

export async function listKnowledgeDatasets(): Promise<KnowledgeDataset[]> {
  const query = new URLSearchParams({
    page: "1",
    page_size: "100",
    include_parsing_status: "true",
  });
  const response = await fetch(knowledgeUrl(`/datasets?${query.toString()}`));
  return readEnvelope<KnowledgeDataset[]>(
    response,
    `Failed to load knowledge bases: ${response.statusText}`,
  );
}

export async function createKnowledgeDataset(
  payload: CreateKnowledgeDatasetRequest,
): Promise<KnowledgeDataset> {
  const response = await fetch(knowledgeUrl("/datasets"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readEnvelope<KnowledgeDataset>(
    response,
    `Failed to create knowledge base: ${response.statusText}`,
  );
}

export async function deleteKnowledgeDataset(datasetId: string): Promise<void> {
  const response = await fetch(
    knowledgeUrl(`/datasets/${encodeURIComponent(datasetId)}`),
    { method: "DELETE" },
  );
  await readEnvelope<unknown>(
    response,
    `Failed to delete knowledge base: ${response.statusText}`,
  );
}

export async function listKnowledgeDocuments(
  datasetId: string,
): Promise<KnowledgeDocumentPage> {
  const query = new URLSearchParams({ page: "1", page_size: "100" });
  const response = await fetch(
    knowledgeUrl(
      `/datasets/${encodeURIComponent(datasetId)}/documents?${query.toString()}`,
    ),
  );
  const data = await readEnvelope<{
    docs: KnowledgeDocument[];
    total: number;
  }>(response, `Failed to load documents: ${response.statusText}`);
  return { documents: data.docs, total: data.total };
}

export async function uploadKnowledgeDocuments(
  datasetId: string,
  files: readonly File[],
): Promise<KnowledgeDocument[]> {
  const body = new FormData();
  for (const file of files) {
    body.append("file", file);
  }
  const response = await fetch(
    knowledgeUrl(`/datasets/${encodeURIComponent(datasetId)}/documents`),
    { method: "POST", body },
  );
  return readEnvelope<KnowledgeDocument[]>(
    response,
    `Failed to upload documents: ${response.statusText}`,
  );
}

export async function parseKnowledgeDocuments(
  datasetId: string,
  documentIds: readonly string[],
): Promise<void> {
  const response = await fetch(
    knowledgeUrl(`/datasets/${encodeURIComponent(datasetId)}/parse`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: documentIds }),
    },
  );
  await readEnvelope<unknown>(
    response,
    `Failed to parse documents: ${response.statusText}`,
  );
}

export async function deleteKnowledgeDocuments(
  datasetId: string,
  documentIds: readonly string[],
): Promise<void> {
  const response = await fetch(
    knowledgeUrl(`/datasets/${encodeURIComponent(datasetId)}/documents`),
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: documentIds }),
    },
  );
  await readEnvelope<unknown>(
    response,
    `Failed to delete documents: ${response.statusText}`,
  );
}
