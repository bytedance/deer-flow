import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/core/auth/AuthProvider";

import { fetchDatasets, fetchDocuments } from "./api";

export function useKnowledgeDatasets() {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["knowledge-base", user?.id, "datasets"],
    queryFn: fetchDatasets,
    enabled: !!user,
    retry: false,
  });
}

export function useKnowledgeDocuments(datasetId: string, page: number) {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["knowledge-base", user?.id, "documents", datasetId, page],
    queryFn: () => fetchDocuments(datasetId, page),
    enabled: !!user && !!datasetId,
    retry: false,
    refetchInterval: (query) =>
      query.state.error
        ? false
        : query.state.data?.documents.some((doc) => doc.status === "parsing")
          ? 3000
          : 15000,
    refetchIntervalInBackground: false,
  });
}
