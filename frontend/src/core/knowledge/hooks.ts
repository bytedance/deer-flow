/**
 * TanStack Query hooks for the knowledge API. Polling cadence lives in the
 * pure `documentsRefetchInterval` (document-stats.ts) so the wiring here
 * stays trivially testable.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "./api";
import { documentsRefetchInterval } from "./document-stats";
import { reindexRefetchInterval } from "./reindex-status";

export function knowledgeBasesKey() {
  return ["knowledge-bases"] as const;
}

export function knowledgeDocumentsKey(kbId: string) {
  return ["knowledge-bases", kbId, "documents"] as const;
}

export function knowledgeChunksKey(kbId: string, docId: string, offset: number, limit: number) {
  return ["knowledge-bases", kbId, "documents", docId, "chunks", { offset, limit }] as const;
}

export function useKnowledgeBases(enabled = true) {
  return useQuery({
    queryKey: knowledgeBasesKey(),
    queryFn: api.listKnowledgeBases,
    enabled,
  });
}

export function supportedFormatsKey() {
  return ["knowledge-bases", "supported-formats"] as const;
}

/** Upload allowlist (Task 6): static data — never goes stale within a session. */
export function useSupportedFormats(enabled = true) {
  return useQuery({
    queryKey: supportedFormatsKey(),
    queryFn: api.getSupportedFormats,
    staleTime: Number.POSITIVE_INFINITY,
    enabled,
  });
}

export function useCreateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createKnowledgeBase,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeBasesKey() });
    },
  });
}

export function useUpdateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kbId, patch }: { kbId: string; patch: { name?: string; description?: string } }) =>
      api.updateKnowledgeBase(kbId, patch),
    onSuccess: (_data, { kbId }) => {
      void queryClient.invalidateQueries({ queryKey: knowledgeBasesKey() });
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (kbId: string) => api.deleteKnowledgeBase(kbId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeBasesKey() });
    },
  });
}

export function useDocuments(kbId: string | null) {
  return useQuery({
    queryKey: knowledgeDocumentsKey(kbId ?? ""),
    queryFn: () => api.listDocuments(kbId!),
    enabled: kbId !== null,
    refetchInterval: (query) => documentsRefetchInterval(query.state.data),
  });
}

export function useUploadDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.uploadDocument(kbId, file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function useDeleteDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => api.deleteDocument(kbId, docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function useRetryDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => api.retryDocument(kbId, docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function knowledgeReindexStatusKey(kbId: string) {
  return ["knowledge-bases", kbId, "reindex-status"] as const;
}

/**
 * 重建进度（spec 2026-09-14 §5 / P4）：只在重建在飞时轮询，空闲不打扰。
 * 设置页的重建入口用它渲染进度行与禁用按钮。
 */
export function useReindexStatus(kbId: string | null) {
  return useQuery({
    queryKey: knowledgeReindexStatusKey(kbId ?? ""),
    queryFn: () => api.getReindexStatus(kbId!),
    enabled: kbId !== null,
    refetchInterval: (query) => reindexRefetchInterval(query.state.data),
  });
}

/**
 * 触发库级重建（202）：202 ack 先于后台任务翻 in-flight 标志返回，立即 refetch
 * 可能仍读到空闲，故补一次 1s 延迟失效。
 */
export function useReindexKnowledgeBase(kbId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.reindexKnowledgeBase(kbId!),
    onSuccess: () => {
      if (kbId === null) return;
      void queryClient.invalidateQueries({ queryKey: knowledgeReindexStatusKey(kbId) });
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: knowledgeReindexStatusKey(kbId) }), 1000);
    },
  });
}
