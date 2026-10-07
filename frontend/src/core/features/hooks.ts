import { useQuery } from "@tanstack/react-query";

import {
  DEFAULT_SCHEDULED_TASKS_FEATURE,
  fetchBrowserControlEnabled,
  fetchConversationReferencesCapability,
  fetchKnowledgeBaseFeature,
  fetchMcpTasksEnabled,
  fetchScheduledTasksFeature,
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

/**
 * Scheduled-task availability. While loading, or when the request fails, the
 * defaults apply (available and running, chat tool off), so the page never
 * flashes an "unavailable" state on a working server.
 */
export function useScheduledTasksFeature() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "scheduled_tasks"],
    queryFn: fetchScheduledTasksFeature,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  const feature = data ?? DEFAULT_SCHEDULED_TASKS_FEATURE;
  return {
    available: feature.available,
    running: feature.running,
    toolEnabled: feature.toolEnabled,
    minIntervalSeconds: feature.minIntervalSeconds,
    isLoading: isPending,
  };
}
