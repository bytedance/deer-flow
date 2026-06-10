import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  connectChannelProvider,
  disconnectChannelConnection,
  listChannelConnections,
  listChannelProviders,
} from "./api";
import type { ChannelProviderId } from "./types";

export const channelProviderQueryKey = ["channelProviders"] as const;
export const channelConnectionsQueryKey = ["channelConnections"] as const;

export function useChannelProviders() {
  const { data, isLoading, error } = useQuery({
    queryKey: channelProviderQueryKey,
    queryFn: () => listChannelProviders(),
  });
  return {
    enabled: data?.enabled ?? false,
    providers: data?.providers ?? [],
    isLoading,
    error,
  };
}

export function useChannelConnections() {
  const { data, isLoading, error } = useQuery({
    queryKey: channelConnectionsQueryKey,
    queryFn: () => listChannelConnections(),
  });
  return { connections: data ?? [], isLoading, error };
}

export function useConnectChannelProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: ChannelProviderId) =>
      connectChannelProvider(provider),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    },
  });
}

export function useDisconnectChannelConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (connectionId: string) =>
      disconnectChannelConnection(connectionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    },
  });
}
