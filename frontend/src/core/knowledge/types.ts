/**
 * Knowledge-base (RAG) types mirroring the Task-8 gateway contract
 * (spec §5.3 / §3.2). Field names stay snake_case to match the API payload
 * exactly — these types are the wire format, not a view model.
 */

export interface KnowledgeBase {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  visibility: "private" | string;
  created_at: string;
}

/** Document status machine (spec §3.6): uploaded → parsing → chunking → indexing → ready / failed. */
export type KnowledgeDocumentStatus = "uploaded" | "parsing" | "chunking" | "indexing" | "ready" | "failed";

// ── P3 per-path sub-status (phase-2 batch-1, spec 2026-08-11 §5) ──────────

/** Vector leg: pending → indexing → done / failed. */
export type VectorPathState = "pending" | "indexing" | "done" | "failed" | string;
/**
 * Caption leg (spec 2026-09-08 §5): image descriptions feeding the vector
 * leg. Written only by documents with images; `degraded` marks a fallback
 * (caption failures beyond the threshold).
 */
export type CaptionLegState = "pending" | "indexing" | "done" | "degraded" | "failed" | string;

/** Per-path indexing sub-status persisted on the document row. */
export interface DocumentPathStatus {
  vector: VectorPathState;
  /** Absent on text documents and legacy rows (spec §5). */
  caption?: CaptionLegState | null;
}

export interface KnowledgeDocument {
  id: string;
  kb_id: string;
  uploader_id: string;
  name: string;
  size_bytes: number;
  storage_path: string;
  status: KnowledgeDocumentStatus;
  progress_percent: number;
  /** Null until indexing finished — the table renders "—" (spec §3.6). */
  chunk_count: number | null;
  /** Failure reason (e.g. the "image caption degraded" marker, spec §3.4). */
  error: string | null;
  /**
   * Per-path sub-status (P3). Null on legacy rows and before the indexing
   * stage — the status cell renders no hover breakdown then (spec §5 兼容).
   */
  path_status: DocumentPathStatus | null;
  /**
   * SHA-256 of the file content (Task 11 duplicate-upload interception).
   * Written at upload time; null on legacy rows (no backfill) — the upload
   * pre-check treats those as "hash unknown" and falls into the conflict
   * branch (replace / keep-both).
   */
  content_hash: string | null;
  created_at: string;
}

export interface KnowledgeChunk {
  chunk_id: string;
  doc_id: string;
  kb_id: string;
  chunk_index: number;
  text: string;
  heading_path: string[];
  page: number | null;
  token_count: number;
  entities: string[];
}

export interface KnowledgeChunkPage {
  items: KnowledgeChunk[];
  total: number;
  offset: number;
  limit: number;
}

/** Reindex ack (spec 2026-09-14 §5 / P4): the 202 from `POST /{kb_id}/reindex`. */
export interface ReindexAck {
  status: "enqueued" | "already_running" | string;
}

/** Live rebuild counters while `in_progress`; the backend sends `null` when idle. */
export interface ReindexProgress {
  documents_total: number;
  documents_done: number;
  chunks_indexed: number;
}

/**
 * Library rebuild status (spec 2026-09-14 §5 / P4). `last_run` is the *previous* run's
 * verdict, so an idle entry can still say whether the last rebuild worked.
 */
export interface ReindexStatus {
  in_progress: boolean;
  last_run: "succeeded" | "failed" | string | null;
  progress: ReindexProgress | null;
}

/** Citation source carried by the retrieval tools' JSON output (spec §4.6). */
export interface KnowledgeCitation {
  chunk_id: string;
  doc_name: string;
  page: number | null;
  heading_path: string[];
  text: string;
  score: number;
  /** Always "chunk" in the first phase (knowledge_search results). */
  source_type?: "chunk";
  /**
   * Backend-assigned citation numbers (rag citation_counter) — INTERNAL
   * handles, never shown to the user. A chunk recalled by multiple calls
   * carries every number it was assigned; the answer's ``[n]`` marks resolve
   * through these to this card, and the card's sorted strip position becomes
   * the display number actually rendered.
   */
  citation_nos?: number[];
}
