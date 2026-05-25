export type KBVisibility = "private" | "tenant" | "public";
export type KBPermissionRole = "viewer" | "editor" | "admin";

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  visibility: KBVisibility;
  status: string;
  owner_user_id: string | null;
  owner_display_name: string | null;
  document_count: number;
  chunk_count: number;
  last_indexed_at: string | null;
  last_search_at: string | null;
  created_at: string;
  updated_at: string;
  my_role: string | null;
  can_write: boolean | null;
  can_admin: boolean | null;
  indexed_count?: number;
  failed_count?: number;
  indexing_count?: number;
  recent_failures?: IndexFailure[];
}

export interface IndexFailure {
  job_id: string;
  doc_id: string;
  error: string | null;
  finished_at: string | null;
}

export interface IndexStats {
  total: number;
  ready: number;
  pending: number;
  indexing: number;
  failed: number;
  cancelled: number;
  failure_by_type: Record<string, number>;
  avg_index_duration_ms: number;
  avg_retrieval_latency_ms: number;
  p95_retrieval_latency_ms: number;
  total_queries: number;
  recent_failures: IndexFailure[];
}

export interface HealthSummaryPerKb {
  kb_id: string;
  kb_name: string;
  total: number;
  ready: number;
  failed: number;
  avg_retrieval_latency_ms: number;
  total_queries: number;
}

export interface HealthSummary {
  total_kbs: number;
  index_success_rate: number;
  failure_by_type: Record<string, number>;
  documents: {
    total: number;
    ready: number;
    pending: number;
    indexing: number;
    failed: number;
    cancelled: number;
  };
  retrieval: {
    avg_latency_ms: number;
    p95_latency_ms: number;
    total_queries: number;
  };
  recent_failures: IndexFailure[];
  per_kb: HealthSummaryPerKb[];
}

export interface KBPermission {
  id: string;
  knowledge_base_id: string;
  tenant_id: string;
  user_id: string;
  role: KBPermissionRole;
  granted_by: string;
  created_at: string;
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
  visibility?: KBVisibility;
}

export interface UpdateKBRequest {
  name?: string;
  description?: string | null;
}

export interface GrantPermissionRequest {
  user_id: string;
  role: KBPermissionRole;
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

export interface DocumentIndexStatus {
  id: string;
  knowledge_base_id: string;
  index_status: string;
  index_error: string | null;
  index_queued_at: string | null;
  last_indexed_at: string | null;
  chunk_count: number;
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
