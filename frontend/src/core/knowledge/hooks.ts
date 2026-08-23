import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";

import { getBackendBaseURL } from "@/core/config";
import { fetchKnowledgeBaseFeature } from "@/core/features/api";
import { useI18n } from "@/core/i18n/hooks";

import {
  createKnowledgeDataset,
  deleteKnowledgeDataset,
  deleteKnowledgeDocuments,
  listKnowledgeDatasets,
  listKnowledgeDocuments,
  parseKnowledgeDocuments,
  uploadKnowledgeDocuments,
} from "./api";
import { applyKnowledgeEventToDatasets, parseKnowledgeEvent } from "./events";
import type { CreateKnowledgeDatasetRequest, KnowledgeDataset } from "./types";

export const KNOWLEDGE_DATASETS_QUERY_KEY = ["knowledge", "datasets"] as const;

export function knowledgeDocumentsQueryKey(datasetId: string) {
  return ["knowledge", "datasets", datasetId, "documents"] as const;
}

export function useKnowledgeBaseEnabled() {
  const query = useQuery({
    queryKey: ["features", "knowledge_base"],
    queryFn: fetchKnowledgeBaseFeature,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    enabled: query.data?.enabled ?? false,
    managementUrl: query.data?.managementUrl ?? null,
    isLoading: query.isPending,
  };
}

export function useKnowledgeDatasets(enabled = true) {
  return useQuery({
    queryKey: KNOWLEDGE_DATASETS_QUERY_KEY,
    queryFn: listKnowledgeDatasets,
    enabled,
    retry: false,
  });
}

export function useKnowledgeDocuments(datasetId: string, enabled = true) {
  return useQuery({
    queryKey: knowledgeDocumentsQueryKey(datasetId),
    queryFn: () => listKnowledgeDocuments(datasetId),
    enabled: enabled && Boolean(datasetId),
    retry: false,
  });
}

export function useCreateKnowledgeDataset() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (payload: CreateKnowledgeDatasetRequest) =>
      createKnowledgeDataset(payload),
    onSuccess: () => {
      toast.success(t.knowledge.create.success);
      void queryClient.invalidateQueries({
        queryKey: KNOWLEDGE_DATASETS_QUERY_KEY,
      });
    },
    onError: (error: Error) => {
      toast.error(`${t.knowledge.errors.create}: ${error.message}`);
    },
  });
}

export function useDeleteKnowledgeDataset() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: deleteKnowledgeDataset,
    onSuccess: () => {
      toast.success(t.knowledge.dataset.deleteSuccess);
      void queryClient.invalidateQueries({
        queryKey: KNOWLEDGE_DATASETS_QUERY_KEY,
      });
    },
    onError: (error: Error) => {
      toast.error(`${t.knowledge.errors.deleteDataset}: ${error.message}`);
    },
  });
}

export function useUploadKnowledgeDocuments(datasetId: string) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (files: readonly File[]) =>
      uploadKnowledgeDocuments(datasetId, files),
    onSuccess: () => {
      toast.success(t.knowledge.upload.success);
      void queryClient.invalidateQueries({
        queryKey: knowledgeDocumentsQueryKey(datasetId),
      });
      void queryClient.invalidateQueries({
        queryKey: KNOWLEDGE_DATASETS_QUERY_KEY,
      });
    },
    onError: (error: Error) => {
      toast.error(`${t.knowledge.errors.upload}: ${error.message}`);
    },
  });
}

export function useParseKnowledgeDocuments(datasetId: string) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (documentIds: readonly string[]) =>
      parseKnowledgeDocuments(datasetId, documentIds),
    onSuccess: () => {
      toast.success(t.knowledge.detail.parseSuccess);
      void queryClient.invalidateQueries({
        queryKey: knowledgeDocumentsQueryKey(datasetId),
      });
      void queryClient.invalidateQueries({
        queryKey: KNOWLEDGE_DATASETS_QUERY_KEY,
      });
    },
    onError: (error: Error) => {
      toast.error(`${t.knowledge.errors.parse}: ${error.message}`);
    },
  });
}

export function useDeleteKnowledgeDocuments(datasetId: string) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (documentIds: readonly string[]) =>
      deleteKnowledgeDocuments(datasetId, documentIds),
    onSuccess: () => {
      toast.success(t.knowledge.detail.deleteSuccess);
      void queryClient.invalidateQueries({
        queryKey: knowledgeDocumentsQueryKey(datasetId),
      });
      void queryClient.invalidateQueries({
        queryKey: KNOWLEDGE_DATASETS_QUERY_KEY,
      });
    },
    onError: (error: Error) => {
      toast.error(`${t.knowledge.errors.deleteDocuments}: ${error.message}`);
    },
  });
}

export function useKnowledgeEvents(enabled: boolean) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;

    const source = new EventSource(
      `${getBackendBaseURL()}/api/knowledge/events`,
      { withCredentials: true },
    );
    const eventTypes = [
      "dataset_parsing_progress",
      "dataset_parsing_completed",
      "dataset_parsing_failed",
    ] as const;

    const listeners = eventTypes.map((type) => {
      const listener = (message: MessageEvent<string>) => {
        const event = parseKnowledgeEvent(type, message);
        if (!event) return;
        queryClient.setQueryData<KnowledgeDataset[]>(
          KNOWLEDGE_DATASETS_QUERY_KEY,
          (datasets) =>
            datasets
              ? applyKnowledgeEventToDatasets(datasets, event)
              : datasets,
        );
        if (event.type !== "dataset_parsing_progress") {
          void queryClient.invalidateQueries({
            queryKey: knowledgeDocumentsQueryKey(event.datasetId),
          });
        }
      };
      source.addEventListener(type, listener as EventListener);
      return { type, listener };
    });

    return () => {
      for (const { type, listener } of listeners) {
        source.removeEventListener(type, listener as EventListener);
      }
      source.close();
    };
  }, [enabled, queryClient]);
}
