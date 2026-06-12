import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createModel,
  deleteModel,
  detectModels,
  loadModels,
  updateModel,
} from "./api";

export function useModels({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["models"],
    queryFn: () => loadModels(),
    enabled,
    refetchOnWindowFocus: false,
  });
  return {
    models: data?.models ?? [],
    tokenUsageEnabled: data?.token_usage.enabled ?? false,
    isLoading,
    error,
  };
}

export function useDetectModels() {
  return useMutation({
    mutationFn: detectModels,
  });
}

export function useCreateModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createModel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useUpdateModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateModel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useDeleteModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteModel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
