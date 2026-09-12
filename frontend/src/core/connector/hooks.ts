import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteConnection,
  listConnections,
  listProviders,
  oauthAuthorize,
  upsertConnection,
} from "./api";

export const connectorProvidersQueryKey = ["connectorProviders"] as const;
export const connectorConnectionsQueryKey = ["connectorConnections"] as const;

export function useConnectorProviders() {
  const { data, isLoading, error } = useQuery({
    queryKey: connectorProvidersQueryKey,
    queryFn: () => listProviders(),
    staleTime: 5 * 60 * 1000,
    // Don't retry — when AnyConnect is unreachable the backend
    // returns an empty list (200), and for real network errors the
    // sidebar shouldn't hammer the gateway with retries.
    retry: false,
  });
  return { providers: data ?? [], isLoading, error };
}

export function useConnectorConnections() {
  const { data, isLoading, error } = useQuery({
    queryKey: connectorConnectionsQueryKey,
    queryFn: () => listConnections(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  return { connections: data ?? [], isLoading, error };
}

export function useSaveConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      service,
      body,
    }: {
      service: string;
      body: Record<string, unknown>;
    }) => upsertConnection(service, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: connectorConnectionsQueryKey,
      });
      void queryClient.invalidateQueries({
        queryKey: connectorProvidersQueryKey,
      });
    },
  });
}

export function useDisconnectConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (service: string) => deleteConnection(service),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: connectorConnectionsQueryKey,
      });
      void queryClient.invalidateQueries({
        queryKey: connectorProvidersQueryKey,
      });
    },
  });
}

export function useOAuthAuthorize() {
  return useMutation({
    mutationFn: (service: string) => oauthAuthorize(service),
  });
}
