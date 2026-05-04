import { fetchGateway } from "../api";
import { getBackendBaseURL } from "../config";

import type {
  DeleteDocumentsRequest,
  IngestRequest,
  IngestResponse,
  RagStatus,
  SearchResponse,
} from "./types";

export async function getRagStatus(): Promise<RagStatus> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/rag/status`);
  if (!response.ok) {
    throw new Error(`Failed to fetch RAG status: ${response.statusText}`);
  }
  return response.json() as Promise<RagStatus>;
}

export async function searchKnowledgeBase(
  query: string,
  collection = "default",
  topK?: number,
  scoreThreshold?: number,
): Promise<SearchResponse> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/rag/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      collection,
      top_k: topK,
      score_threshold: scoreThreshold,
    }),
  });
  if (!response.ok) {
    throw new Error(`Failed to search knowledge base: ${response.statusText}`);
  }
  return response.json() as Promise<SearchResponse>;
}

export async function ingestDocument(
  req: IngestRequest,
): Promise<IngestResponse> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/rag/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!response.ok) {
    throw new Error(`Failed to ingest document: ${response.statusText}`);
  }
  return response.json() as Promise<IngestResponse>;
}

export async function listCollections(): Promise<string[]> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/rag/collections`,
  );
  if (!response.ok) {
    throw new Error(`Failed to list collections: ${response.statusText}`);
  }
  return response.json() as Promise<string[]>;
}

export async function deleteCollection(name: string): Promise<void> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/rag/collections/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(`Failed to delete collection: ${response.statusText}`);
  }
}

export async function deleteDocuments(req: DeleteDocumentsRequest): Promise<void> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/rag/documents`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    },
  );
  if (!response.ok) {
    throw new Error(`Failed to delete documents: ${response.statusText}`);
  }
}
