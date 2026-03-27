import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  discoverModelServiceProvider,
  loadModelServicesConfig,
  syncModelServiceProvider,
  testModelServiceProvider,
  updateModelServiceDefaults,
  updateModelServicesConfig,
} from "./api";

export function useModelServicesConfig() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["modelServicesConfig"],
    queryFn: () => loadModelServicesConfig(),
    refetchOnWindowFocus: false,
  });
  return { config: data, isLoading, error };
}

export function useSaveModelServicesConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateModelServicesConfig,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["modelServicesConfig"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useTestModelServiceProvider() {
  return useMutation({
    mutationFn: testModelServiceProvider,
  });
}

export function useSyncModelServiceProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: syncModelServiceProvider,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["modelServicesConfig"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useDiscoverModelServiceProvider() {
  return useMutation({
    mutationFn: discoverModelServiceProvider,
  });
}

export function useUpdateModelServiceDefaults() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateModelServiceDefaults,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["modelServicesConfig"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
