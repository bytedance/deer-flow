export interface RagStatus {
  enabled: boolean;
  backend: string;
  embedding_model: string;
  collections: string[];
}

export interface SearchResult {
  rank: number;
  content: string;
  score: number;
  source: string;
}

export interface SearchResponse {
  query: string;
  collection: string;
  results: SearchResult[];
}

export interface IngestRequest {
  text: string;
  source_name: string;
  collection?: string;
  metadata?: Record<string, unknown>;
}

export interface IngestResponse {
  collection: string;
  source: string;
  chunk_count: number;
  chunk_ids: string[];
  error?: string | null;
}

export interface DeleteDocumentsRequest {
  collection: string;
  chunk_ids: string[];
}
