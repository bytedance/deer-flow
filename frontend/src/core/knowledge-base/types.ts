export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  visibility: string;
  status: string;
  document_count: number;
  chunk_count: number;
  last_indexed_at: string | null;
  last_search_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseDocument {
  id: string;
  knowledge_base_id: string;
  title: string;
  content: string;
  content_format: string;
  source_name: string | null;
  version: number;
  chunk_count: number;
  index_status: string;
  index_error: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateKBRequest {
  name: string;
  description?: string;
  visibility?: string;
}

export interface UpdateKBRequest {
  name?: string;
  description?: string | null;
  visibility?: string;
}

export interface CreateDocumentRequest {
  title: string;
  content: string;
  content_format?: string;
  source_name?: string;
}

export interface UpdateDocumentRequest {
  title?: string;
  content?: string;
  content_format?: string;
  source_name?: string | null;
}

export interface SearchResultItem {
  chunk_id: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  results: SearchResultItem[];
  query: string;
  knowledge_base_id: string;
}
