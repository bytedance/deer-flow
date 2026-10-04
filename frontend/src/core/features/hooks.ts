import { useQuery } from "@tanstack/react-query";

import {
  fetchBrowserControlEnabled,
  fetchConversationReferencesCapability,
  fetchImageGenerationManagementEnabled,
  fetchKnowledgeBaseFeature,
  fetchMcpTasksEnabled,
  fetchSubagentBatchesCapability,
} from "./api";

export function useBrowserControlEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "browser_control"],
    queryFn: () => fetchBrowserControlEnabled(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useMcpTasksEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "mcp_tasks"],
    queryFn: () => fetchMcpTasksEnabled(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useImageGenerationManagementEnabled(enabled: boolean) {
  const { data } = useQuery({
    queryKey: ["features", "image_generation_management"],
    queryFn: fetchImageGenerationManagementEnabled,
    enabled,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return data ?? false;
}

export function useSubagentBatchesCapability() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "subagent_batches"],
    queryFn: () => fetchSubagentBatchesCapability(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    repositoryAvailable: data?.repositoryAvailable ?? false,
    workerRunning: data?.workerRunning ?? false,
    maxRunning: data?.maxRunning ?? 0,
    isLoading: isPending,
  };
}

export function useConversationReferencesCapability() {
  const { data, isPending, isSuccess, error, refetch } = useQuery({
    queryKey: ["features", "conversation_references"],
    queryFn: () => fetchConversationReferencesCapability(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    enabled: isSuccess && (data?.enabled ?? false),
    maxReferences: data?.maxReferences ?? 0,
    isLoading: isPending,
    isSuccess,
    error,
    refetch,
  };
}

export function useKnowledgeBaseEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "knowledge_base"],
    queryFn: fetchKnowledgeBaseFeature,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    scopeSelectionEnabled: data?.scopeSelectionEnabled ?? false,
    isLoading: isPending,
  };
}
