import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import {
  createDocument,
  createKnowledgeBase,
  deleteDocument,
  deleteKnowledgeBase,
  grantPermission,
  listAdminKnowledgeBases,
  listDocuments,
  listKnowledgeBases,
  listPermissions,
  reindexDocument,
  revokePermission,
  searchKnowledgeBase,
  updateDocument,
  updateKnowledgeBase,
  uploadDocument,
} from "./api";
import type {
  CreateDocumentRequest,
  CreateKBRequest,
  GrantPermissionRequest,
  KnowledgeBaseDocument,
  UpdateDocumentRequest,
  UpdateKBRequest,
} from "./types";

const ACTIVE_DOCUMENT_INDEX_STATUSES = new Set(["pending", "indexing"]);
const DOCUMENT_INDEXING_POLL_INTERVAL_MS = 2000;

function hasActiveDocumentIndexing(
  documents: Array<Pick<KnowledgeBaseDocument, "index_status">> | undefined,
): boolean {
  return (
    documents?.some((document) =>
      ACTIVE_DOCUMENT_INDEX_STATUSES.has(document.index_status),
    ) ?? false
  );
}

function getDocumentRefetchInterval(
  documents: Array<Pick<KnowledgeBaseDocument, "index_status">> | undefined,
): number | false {
  return hasActiveDocumentIndexing(documents)
    ? DOCUMENT_INDEXING_POLL_INTERVAL_MS
    : false;
}

function getDocumentStatsSignature(
  documents:
    | Array<
        Pick<KnowledgeBaseDocument, "id" | "index_status" | "chunk_count">
      >
    | undefined,
): string {
  return (documents ?? [])
    .map(
      (document) =>
        `${document.id}:${document.index_status}:${document.chunk_count}`,
    )
    .sort()
    .join("|");
}

export const __test_only = {
  hasActiveDocumentIndexing,
  getDocumentRefetchInterval,
  getDocumentStatsSignature,
};

export function useKnowledgeBases({
  enabled = true,
}: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: listKnowledgeBases,
    enabled,
    refetchOnWindowFocus: false,
  });
  return {
    knowledgeBases: data ?? [],
    isLoading,
    error,
  };
}

export function useCreateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateKBRequest) => createKnowledgeBase(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
    },
  });
}

export function useUpdateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, request }: { id: string; request: UpdateKBRequest }) =>
      updateKnowledgeBase(id, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
    },
  });
}

export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteKnowledgeBase(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
    },
  });
}

export function useDocuments(kbId: string, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  const lastSummarySignatureRef = useRef<string | null>(null);
  const { data, isLoading, error } = useQuery<KnowledgeBaseDocument[]>({
    queryKey: ["knowledge-bases", kbId, "documents"],
    queryFn: () => listDocuments(kbId),
    enabled: enabled && !!kbId,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => getDocumentRefetchInterval(query.state.data),
  });

  useEffect(() => {
    if (!enabled || !kbId || !data) {
      lastSummarySignatureRef.current = null;
      return;
    }
    const nextSignature = getDocumentStatsSignature(data);
    if (nextSignature === lastSummarySignatureRef.current) {
      return;
    }
    lastSummarySignatureRef.current = nextSignature;
    void queryClient.invalidateQueries({
      queryKey: ["knowledge-bases"],
      refetchType: "active",
    });
  }, [data, enabled, kbId, queryClient]);

  return {
    documents: data ?? [],
    isLoading,
    error,
  };
}

export function useCreateDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateDocumentRequest) =>
      createDocument(kbId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", kbId, "documents"],
      });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
    },
  });
}

export function useUpdateDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      docId,
      request,
    }: {
      docId: string;
      request: UpdateDocumentRequest;
    }) => updateDocument(kbId, docId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", kbId, "documents"],
      });
    },
  });
}

export function useDeleteDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => deleteDocument(kbId, docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", kbId, "documents"],
      });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
    },
  });
}

export function useReindexDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => reindexDocument(kbId, docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", kbId, "documents"],
      });
    },
  });
}

export function useSearchKnowledgeBase(kbId: string) {
  return useMutation({
    mutationFn: ({ query, topK = 5 }: { query: string; topK?: number }) =>
      searchKnowledgeBase(kbId, query, topK),
  });
}

export function useUploadDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, title }: { file: File; title?: string }) =>
      uploadDocument(kbId, file, title),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", kbId, "documents"],
      });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Permissions
// ---------------------------------------------------------------------------

export function usePermissions(kbId: string, { enabled = true } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["knowledge-bases", kbId, "permissions"],
    queryFn: () => listPermissions(kbId),
    enabled: enabled && !!kbId,
    refetchOnWindowFocus: false,
  });
  return {
    permissions: data ?? [],
    isLoading,
    error,
  };
}

export function useGrantPermission(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: GrantPermissionRequest) =>
      grantPermission(kbId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", kbId, "permissions"],
      });
    },
  });
}

export function useRevokePermission(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (targetUserId: string) => revokePermission(kbId, targetUserId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", kbId, "permissions"],
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export function useAdminKnowledgeBases({
  enabled = true,
  visibility,
  limit,
  offset,
}: {
  enabled?: boolean;
  visibility?: string;
  limit?: number;
  offset?: number;
} = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["knowledge-bases", "admin", { visibility, limit, offset }],
    queryFn: () => listAdminKnowledgeBases({ visibility, limit, offset }),
    enabled,
    refetchOnWindowFocus: false,
  });
  return {
    knowledgeBases: data ?? [],
    isLoading,
    error,
  };
}
