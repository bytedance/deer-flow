import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  configureChannelProvider,
  connectChannelProvider,
  disconnectChannelConnection,
  disconnectChannelProvider,
  listChannelConnections,
  listChannelProviders,
} from "./api";
import type { ChannelProviderId, ChannelRuntimeConfigValues } from "./types";

export const channelProviderQueryKey = ["channelProviders"] as const;
export const channelConnectionsQueryKey = ["channelConnections"] as const;
const CONNECT_POLL_INTERVAL_MS = 2000;

function pollChannelConnectionUntilResolved(
  queryClient: ReturnType<typeof useQueryClient>,
  provider: ChannelProviderId,
  expiresInSeconds: number,
) {
  const deadline = Date.now() + Math.max(1, expiresInSeconds) * 1000;

  const poll = () => {
    window.setTimeout(() => {
      void Promise.all([
        queryClient.fetchQuery({
          queryKey: channelProviderQueryKey,
          queryFn: () => listChannelProviders(),
        }),
        queryClient.fetchQuery({
          queryKey: channelConnectionsQueryKey,
          queryFn: () => listChannelConnections(),
        }),
      ])
        .then(([providersResponse, connections]) => {
          const providerConnected = providersResponse.providers.some(
            (item) =>
              item.provider === provider &&
              item.connection_status === "connected",
          );
          const connectionConnected = connections.some(
            (item) => item.provider === provider && item.status === "connected",
          );
          if (
            providerConnected ||
            connectionConnected ||
            Date.now() >= deadline
          ) {
            return;
          }
          poll();
        })
        .catch(() => {
          if (Date.now() < deadline) {
            poll();
          }
        });
    }, CONNECT_POLL_INTERVAL_MS);
  };

  poll();
}

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
    onSuccess: (result, provider) => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
      pollChannelConnectionUntilResolved(
        queryClient,
        provider,
        result.expires_in,
      );
    },
  });
}

export function useConfigureChannelProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      provider,
      values,
    }: {
      provider: ChannelProviderId;
      values: ChannelRuntimeConfigValues;
    }) => configureChannelProvider(provider, values),
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

export function useDisconnectChannelProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (provider: ChannelProviderId) =>
      disconnectChannelProvider(provider),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    },
  });
}
