import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteMemoryFact,
  loadMemory,
  loadMemoryConfig,
  updateMemoryConfig,
} from "./api";
import type { MemoryConfig } from "./types";

export function useMemory() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory"],
    queryFn: () => loadMemory(),
  });
  return { memory: data ?? null, isLoading, error };
}

export function useMemoryConfig() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory-config"],
    queryFn: () => loadMemoryConfig(),
  });

  const { mutate: updateConfig, isPending: isUpdating } = useMutation({
    mutationFn: (updates: Partial<MemoryConfig>) => updateMemoryConfig(updates),
    onSuccess: (updated) => {
      queryClient.setQueryData(["memory-config"], updated);
    },
  });

  return { config: data ?? null, isLoading, error, updateConfig, isUpdating };
}

export function useDeleteMemoryFact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (factId: string) => deleteMemoryFact(factId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
  });
}
