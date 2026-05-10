import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
  UpdateDocumentRequest,
  UpdateKBRequest,
} from "./types";

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
  const { data, isLoading, error } = useQuery({
    queryKey: ["knowledge-bases", kbId, "documents"],
    queryFn: () => listDocuments(kbId),
    enabled: enabled && !!kbId,
    refetchOnWindowFocus: false,
  });
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
