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

export const larkIntegrationQueryKey = ["integrations", "lark"] as const;

export function useLarkIntegrationStatus() {
  return useQuery({
    queryKey: larkIntegrationQueryKey,
    queryFn: loadLarkIntegrationStatus,
  });
}

export function useInstallLarkIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: installLarkIntegration,
    onSuccess: async (result) => {
      queryClient.setQueryData(larkIntegrationQueryKey, result.status);
      await queryClient.invalidateQueries({
        queryKey: larkIntegrationQueryKey,
      });
      await queryClient.invalidateQueries({ queryKey: ["skills"] });
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
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: completeLarkConfiguration,
    onSuccess: async (result) => {
      queryClient.setQueryData(larkIntegrationQueryKey, result.status);
      await queryClient.invalidateQueries({
        queryKey: larkIntegrationQueryKey,
      });
    },
  });
}

export function useSetLarkAppCredentials() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: setLarkAppCredentials,
    // Only seed the switched status; do not invalidate. Switching is always
    // followed by the browser auth flow, whose completion writes the
    // authoritative status. A refetch here would race that write and could
    // flash the UI back to the pre-authorization state.
    onSuccess: (result) => {
      queryClient.setQueryData(larkIntegrationQueryKey, result.status);
    },
  });
}

export function useCompleteLarkAuthorization() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: completeLarkAuthorization,
    onSuccess: (result) => {
      queryClient.setQueryData(larkIntegrationQueryKey, result.status);
    },
  });
}
