import { useQuery } from "@tanstack/react-query";

import { fetchKnowledgeBaseFeature } from "@/core/features/api";

export function useKnowledgeBaseEnabled() {
  const query = useQuery({
    queryKey: ["features", "knowledge_base"],
    queryFn: fetchKnowledgeBaseFeature,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    scopeSelectionEnabled: query.data?.scopeSelectionEnabled ?? false,
    isLoading: query.isPending,
  };
}
