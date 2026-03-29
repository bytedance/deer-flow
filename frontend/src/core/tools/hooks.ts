import { useQuery } from "@tanstack/react-query";

import { loadConfiguredTools } from "./api";

export function useConfiguredTools() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["configuredTools"],
    queryFn: () => loadConfiguredTools(),
  });
  return { tools: data ?? [], isLoading, error };
}
