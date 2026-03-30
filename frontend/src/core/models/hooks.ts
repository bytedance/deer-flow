import { useQuery } from "@tanstack/react-query";

import { modelsQueryOptions } from "./query";

export function useModels({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    ...modelsQueryOptions(),
    enabled,
  });
  return { models: data ?? [], isLoading, error };
}
