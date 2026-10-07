/**
 * Pure derivations over the document table (spec §3.6): the bottom stats row
 * is aggregated client-side, and terminal-state classification is shared by
 * the polling hook and the status badge.
 */
import type { KnowledgeDocument } from "./types";

export interface DocumentStats {
  total: number;
  ready: number;
  failed: number;
  /** Documents in a non-terminal pipeline state (uploaded/parsing/chunking/indexing). */
  inProgress: number;
  totalBytes: number;
  totalChunks: number;
}

export function isDocumentTerminal(
  doc: Pick<KnowledgeDocument, "status">,
): boolean {
  return doc.status === "ready" || doc.status === "failed";
}

export function aggregateDocumentStats(
  docs: readonly KnowledgeDocument[],
): DocumentStats {
  let ready = 0;
  let failed = 0;
  let inProgress = 0;
  let totalBytes = 0;
  let totalChunks = 0;
  for (const doc of docs) {
    if (doc.status === "ready") ready += 1;
    else if (doc.status === "failed") failed += 1;
    else inProgress += 1;
    totalBytes += doc.size_bytes;
    totalChunks += doc.chunk_count ?? 0;
  }
  return {
    total: docs.length,
    ready,
    failed,
    inProgress,
    totalBytes,
    totalChunks,
  };
}

/** Polling cadence for the document list while any doc is mid-pipeline. */
export const DOCUMENTS_POLL_INTERVAL_MS = 3000;

/** TanStack Query ``refetchInterval`` decision for the documents query. */
export function documentsRefetchInterval(
  docs: readonly KnowledgeDocument[] | undefined,
): number | false {
  if (!docs) return false;
  if (docs.some((doc) => !isDocumentTerminal(doc)))
    return DOCUMENTS_POLL_INTERVAL_MS;
  return false;
}

/** Human-readable byte size (1024-based, one decimal for KB+). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kib = bytes / 1024;
  if (kib < 1024) return `${kib.toFixed(1)} KB`;
  const mib = kib / 1024;
  if (mib < 1024) return `${mib.toFixed(1)} MB`;
  return `${(mib / 1024).toFixed(1)} GB`;
}

/**
 * Fixed-unit KB for the size column (2026-08-31): bare thousands-grouped
 * number (the caller appends the " KB" suffix; the header stays unit-less)
 * so the right edge aligns. Sub-1KB files round up to 1 (Windows
 * convention — no misleading 0.2); exact bytes go to the hover tooltip.
 */
export function formatKb(bytes: number): string {
  if (bytes <= 0) return "0";
  if (bytes < 1024) return "1";
  return Math.round(bytes / 1024).toLocaleString();
}

/**
 * Fixed-unit MB for the size column (2026-09-02, 方案 Task 2): the caller
 * appends the " MB" suffix (the header stays unit-less) so the right edge
 * aligns. >=0.1MB keeps one decimal; below that two decimals to avoid a
 * misleading "0.0". Two-state KB<->MB is a user choice — tiny files
 * legitimately show 0.00 MB (exact bytes stay in the hover tooltip).
 */
export function formatMb(bytes: number): string {
  if (bytes <= 0) return "0";
  const mib = bytes / 1_048_576;
  return mib >= 0.1 ? mib.toFixed(1) : mib.toFixed(2);
}
