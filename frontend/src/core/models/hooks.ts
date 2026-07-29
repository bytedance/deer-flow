import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteAdminModel,
  loadAdminModels,
  loadModels,
  ModelsAdminRequestError,
  updateAdminModels,
} from "./api";
import type { FullModelConfig } from "./types";

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

export function useAdminModels({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["adminModels"],
    queryFn: () => loadAdminModels(),
    enabled,
    refetchOnWindowFocus: false,
    retry: (count, err) =>
      !(err instanceof ModelsAdminRequestError) && count < 3,
  });
  return {
    models: data?.models ?? [],
    tokenUsageEnabled: data?.token_usage.enabled ?? false,
    isLoading,
    error,
  };
}

export function useUpdateModels() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (models: FullModelConfig[]) => {
      return updateAdminModels(models);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["adminModels"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useDeleteModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      await deleteAdminModel(name);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["adminModels"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
