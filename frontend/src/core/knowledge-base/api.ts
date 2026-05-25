import { fetchGateway } from "../api";
import { getBackendBaseURL } from "../config";
import {
  ConversionError,
  type ConversionErrorBody,
} from "../uploads/conversion-errors";

import type {
  CreateDocumentRequest,
  CreateKBRequest,
  DocumentIndexStatus,
  GrantPermissionRequest,
  HealthSummary,
  IndexStats,
  KBPermission,
  KnowledgeBase,
  KnowledgeBaseDocument,
  SearchResponse,
  UpdateDocumentRequest,
  UpdateKBRequest,
} from "./types";

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases`,
  );
  if (!response.ok) {
    throw new Error(
      `Failed to list knowledge bases: ${response.statusText}`,
    );
  }
  return response.json() as Promise<KnowledgeBase[]>;
}

export async function getKnowledgeBase(id: string): Promise<KnowledgeBase> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${id}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to get knowledge base: ${res.statusText}`);
  }
  return res.json() as Promise<KnowledgeBase>;
}

export async function createKnowledgeBase(
  request: CreateKBRequest,
): Promise<KnowledgeBase> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to create knowledge base: ${res.statusText}`,
    );
  }
  return res.json() as Promise<KnowledgeBase>;
}

export async function updateKnowledgeBase(
  id: string,
  request: UpdateKBRequest,
): Promise<KnowledgeBase> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${id}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to update knowledge base: ${res.statusText}`,
    );
  }
  return res.json() as Promise<KnowledgeBase>;
}

export async function deleteKnowledgeBase(id: string): Promise<void> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${id}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(`Failed to delete knowledge base: ${res.statusText}`);
  }
}

export async function listDocuments(
  kbId: string,
): Promise<KnowledgeBaseDocument[]> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents`,
  );
  if (!res.ok) {
    throw new Error(`Failed to list documents: ${res.statusText}`);
  }
  return res.json() as Promise<KnowledgeBaseDocument[]>;
}

export async function getDocument(
  kbId: string,
  docId: string,
): Promise<KnowledgeBaseDocument> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents/${docId}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to get document: ${res.statusText}`);
  }
  return res.json() as Promise<KnowledgeBaseDocument>;
}

export async function getDocumentIndexStatus(
  kbId: string,
  docId: string,
): Promise<DocumentIndexStatus> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents/${docId}/index-status`,
  );
  if (!res.ok) {
    throw new Error(`Failed to get document index status: ${res.statusText}`);
  }
  return res.json() as Promise<DocumentIndexStatus>;
}

export async function createDocument(
  kbId: string,
  request: CreateDocumentRequest,
): Promise<KnowledgeBaseDocument> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to create document: ${res.statusText}`,
    );
  }
  return res.json() as Promise<KnowledgeBaseDocument>;
}

export async function updateDocument(
  kbId: string,
  docId: string,
  request: UpdateDocumentRequest,
): Promise<KnowledgeBaseDocument> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents/${docId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to update document: ${res.statusText}`,
    );
  }
  return res.json() as Promise<KnowledgeBaseDocument>;
}

export async function deleteDocument(
  kbId: string,
  docId: string,
): Promise<void> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents/${docId}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(`Failed to delete document: ${res.statusText}`);
  }
}

export async function reindexDocument(
  kbId: string,
  docId: string,
): Promise<void> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents/${docId}/reindex`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(`Failed to reindex document: ${res.statusText}`);
  }
}

export async function searchKnowledgeBase(
  kbId: string,
  query: string,
  topK = 5,
): Promise<SearchResponse> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: topK }),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to search knowledge base: ${res.statusText}`,
    );
  }
  return res.json() as Promise<SearchResponse>;
}

export async function uploadDocument(
  kbId: string,
  file: File,
  title?: string,
): Promise<KnowledgeBaseDocument> {
  const formData = new FormData();
  formData.append("file", file);
  if (title) {
    formData.append("title", title);
  }

  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/documents/upload`,
    {
      method: "POST",
      body: formData,
    },
  );
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: ConversionErrorBody | string;
    };
    const detail = body.detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      // Conversion failed inside _convert_binary_file (Sprint C.1.2 / C.3.2).
      // Surface the stable code so the UI shows a localised toast.
      throw new ConversionError(detail);
    }
    throw new Error(
      (typeof detail === "string" ? detail : undefined) ??
        `Failed to upload document: ${res.statusText}`,
    );
  }
  return res.json() as Promise<KnowledgeBaseDocument>;
}

// ---------------------------------------------------------------------------
// Permissions
// ---------------------------------------------------------------------------

export async function listPermissions(kbId: string): Promise<KBPermission[]> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/permissions`,
  );
  if (!res.ok) {
    throw new Error(`Failed to list permissions: ${res.statusText}`);
  }
  return res.json() as Promise<KBPermission[]>;
}

export async function grantPermission(
  kbId: string,
  request: GrantPermissionRequest,
): Promise<KBPermission> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/permissions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to grant permission: ${res.statusText}`,
    );
  }
  return res.json() as Promise<KBPermission>;
}

export async function revokePermission(
  kbId: string,
  targetUserId: string,
): Promise<void> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/permissions/${targetUserId}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to revoke permission: ${res.statusText}`,
    );
  }
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export async function listAdminKnowledgeBases(params?: {
  visibility?: string;
  limit?: number;
  offset?: number;
}): Promise<KnowledgeBase[]> {
  const searchParams = new URLSearchParams();
  if (params?.visibility) searchParams.set("visibility", params.visibility);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));

  const qs = searchParams.toString();
  const url = `${getBackendBaseURL()}/api/knowledge-bases/admin/all${qs ? `?${qs}` : ""}`;
  const res = await fetchGateway(url);
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to list admin knowledge bases: ${res.statusText}`,
    );
  }
  return res.json() as Promise<KnowledgeBase[]>;
}

// ---------------------------------------------------------------------------
// Index stats (observability)
// ---------------------------------------------------------------------------

export async function getIndexStats(kbId: string): Promise<IndexStats> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/${kbId}/index-stats`,
  );
  if (!res.ok) {
    throw new Error(`Failed to get index stats: ${res.statusText}`);
  }
  return res.json() as Promise<IndexStats>;
}

export async function getHealthSummary(): Promise<HealthSummary> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/knowledge-bases/health-summary`,
  );
  if (!res.ok) {
    throw new Error(`Failed to get health summary: ${res.statusText}`);
  }
  return res.json() as Promise<HealthSummary>;
}
