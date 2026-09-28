import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  completeLarkAuthorization,
  completeLarkConfiguration,
  installLarkIntegration,
  loadLarkIntegrationStatus,
  setLarkAppCredentials,
  startLarkAuthorization,
  startLarkConfiguration,
} from "./api";
import { cacheLarkMutationStatus, larkIntegrationQueryKey } from "./cache";

export function useLarkIntegrationStatus() {
  return useQuery({
    queryKey: larkIntegrationQueryKey,
    queryFn: ({ signal }) => loadLarkIntegrationStatus(signal),
  });
}

export function useInstallLarkIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: installLarkIntegration,
    onSuccess: async (result) => {
      cacheLarkMutationStatus(queryClient, result.status);
      await queryClient.invalidateQueries({
        queryKey: larkIntegrationQueryKey,
      });
      await queryClient.invalidateQueries({ queryKey: ["skills"] });
      await queryClient.invalidateQueries({ queryKey: ["capabilities"] });
    },
  });
}

export function useStartLarkAuthorization() {
  return useMutation({
    mutationFn: startLarkAuthorization,
  });
}

export function useStartLarkConfiguration() {
  return useMutation({
    mutationFn: startLarkConfiguration,
  });
}

export function useCompleteLarkConfiguration() {
  return useMutation({
    mutationFn: completeLarkConfiguration,
  });
}

export function useSetLarkAppCredentials() {
  return useMutation({
    mutationFn: setLarkAppCredentials,
  });
}

export function useCompleteLarkAuthorization() {
  return useMutation({
    mutationFn: completeLarkAuthorization,
  });
}
