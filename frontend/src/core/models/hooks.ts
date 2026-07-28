import { useQuery } from "@tanstack/react-query";

import { loadModels } from "./api";

export function useModels({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["models"],
    queryFn: () => loadModels(),
    enabled,
    refetchOnWindowFocus: false,
    // Model config changes rarely and every subtask card mounts its own
    // observer of this query; without a staleTime each newly-mounted card would
    // refetch /api/models on mount (default staleTime: 0). Treat the list as
    // fresh for the session so a long conversation with many cards issues one
    // request, not one per card.
    staleTime: Infinity,
  });
  return {
    models: data?.models ?? [],
    tokenUsageEnabled: data?.token_usage.enabled ?? false,
    isLoading,
    error,
  };
}
