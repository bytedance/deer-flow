/**
 * REST client for the knowledge-base management API (spec §5.3).
 * Follows the `core/memory/api.ts` pattern: the shared fetcher owns CSRF +
 * credentials + 401 redirect; this module owns paths, bodies, and error
 * detail surfacing.
 */
import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import type {
  KnowledgeBase,
  KnowledgeChunkPage,
  KnowledgeDocument,
  ReindexAck,
  ReindexStatus,
} from "./types";

function formatErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const record = item as Record<string, unknown>;
          if (typeof record.msg === "string") return record.msg;
        }
        return null;
      })
      .filter(Boolean);
    return parts.length > 0 ? parts.join("; ") : null;
  }
  return null;
}

function buildResponseError(response: Response, detail: unknown, fallbackMessage: string): Error {
  const detailMessage = formatErrorDetail(detail);
  return new Error(detailMessage ?? `${fallbackMessage}: ${response.statusText}`);
}

async function readResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw buildResponseError(response, errorData.detail, fallbackMessage);
  }
  return response.json() as Promise<T>;
}

async function readEmptyResponse(response: Response, fallbackMessage: string): Promise<void> {
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw buildResponseError(response, errorData.detail, fallbackMessage);
  }
}

function kbUrl(kbId: string, suffix = ""): string {
  return `${getBackendBaseURL()}/api/knowledge-bases/${encodeURIComponent(kbId)}${suffix}`;
}

export function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  return fetch(`${getBackendBaseURL()}/api/knowledge-bases`).then((response) =>
    readResponse<KnowledgeBase[]>(response, "Failed to list knowledge bases"),
  );
}

export function getSupportedFormats(): Promise<{ suffixes: string[] }> {
  return fetch(`${getBackendBaseURL()}/api/knowledge-bases/supported-formats`).then(
    (response) => readResponse<{ suffixes: string[] }>(response, "Failed to load supported formats"),
  );
}

export function createKnowledgeBase(input: { name: string; description?: string }): Promise<KnowledgeBase> {
  return fetch(`${getBackendBaseURL()}/api/knowledge-bases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((response) => readResponse<KnowledgeBase>(response, "Failed to create knowledge base"));
}

export function getKnowledgeBase(kbId: string): Promise<KnowledgeBase> {
  return fetch(kbUrl(kbId)).then((response) =>
    readResponse<KnowledgeBase>(response, "Failed to load knowledge base"),
  );
}

export function updateKnowledgeBase(
  kbId: string,
  patch: { name?: string; description?: string },
): Promise<KnowledgeBase> {
  return fetch(kbUrl(kbId), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  }).then((response) => readResponse<KnowledgeBase>(response, "Failed to update knowledge base"));
}

export async function deleteKnowledgeBase(kbId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId), { method: "DELETE" });
  await readEmptyResponse(response, "Failed to delete knowledge base");
}

export function listDocuments(kbId: string): Promise<KnowledgeDocument[]> {
  return fetch(kbUrl(kbId, "/documents")).then((response) =>
    readResponse<KnowledgeDocument[]>(response, "Failed to list documents"),
  );
}

export function uploadDocument(kbId: string, file: File): Promise<KnowledgeDocument> {
  const form = new FormData();
  form.append("file", file);
  return fetch(kbUrl(kbId, "/documents"), {
    method: "POST",
    body: form,
  }).then((response) => readResponse<KnowledgeDocument>(response, "Failed to upload document"));
}

export async function deleteDocument(kbId: string, docId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId, `/documents/${encodeURIComponent(docId)}`), {
    method: "DELETE",
  });
  await readEmptyResponse(response, "Failed to delete document");
}

export function retryDocument(kbId: string, docId: string): Promise<KnowledgeDocument> {
  return fetch(kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/retry`), {
    method: "POST",
  }).then((response) => readResponse<KnowledgeDocument>(response, "Failed to retry document"));
}

export function listDocumentChunks(
  kbId: string,
  docId: string,
  options: { offset?: number; limit?: number } = {},
): Promise<KnowledgeChunkPage> {
  const query = new URLSearchParams();
  if (options.offset != null) query.set("offset", String(options.offset));
  if (options.limit != null) query.set("limit", String(options.limit));
  const suffix = `/documents/${encodeURIComponent(docId)}/chunks${query.size ? `?${query}` : ""}`;
  return fetch(kbUrl(kbId, suffix)).then((response) =>
    readResponse<KnowledgeChunkPage>(response, "Failed to list document chunks"),
  );
}

export function documentFileUrl(kbId: string, docId: string, ref: string): string {
  const encodedRef = ref.split("/").map(encodeURIComponent).join("/");
  return kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/files/${encodedRef}`);
}

export function documentSourceUrl(kbId: string, docId: string): string {
  return kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/source`);
}

export function downloadDocumentSource(kbId: string, docId: string): void {
  // 锚点导航而非 fetch+blob：让浏览器原生下载处理 Content-Disposition，
  // 大文件不经过 JS 内存。
  const anchor = document.createElement("a");
  anchor.href = documentSourceUrl(kbId, docId);
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

export function reindexKnowledgeBase(kbId: string): Promise<ReindexAck> {
  return fetch(kbUrl(kbId, "/reindex"), { method: "POST" }).then((response) =>
    readResponse<ReindexAck>(response, "Failed to start reindex"),
  );
}

export function getReindexStatus(kbId: string): Promise<ReindexStatus> {
  return fetch(kbUrl(kbId, "/reindex/status")).then((response) =>
    readResponse<ReindexStatus>(response, "Failed to load reindex status"),
  );
}
