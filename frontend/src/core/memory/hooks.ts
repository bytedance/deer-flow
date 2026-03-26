import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { clearAllMemory, deleteMemoryFact, loadMemory } from "./api";

export function useMemory() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory"],
    queryFn: () => loadMemory(),
  });
  return { memory: data ?? null, isLoading, error };
}

export function useDeleteFact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (factId: string) => deleteMemoryFact(factId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
  });
}

export function useClearMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => clearAllMemory(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
  });
}
