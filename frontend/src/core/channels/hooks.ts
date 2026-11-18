import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import {
  configureChannelProvider,
  connectChannelProvider,
  disconnectChannelConnection,
  disconnectChannelProvider,
  listChannelConnections,
  listChannelProviders,
} from "./api";
import { startConnectionPoll, type ConnectPollHandle } from "./connect-poll";
import type { ChannelProviderId, ChannelRuntimeConfigValues } from "./types";

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
  const pollersRef = useRef<Map<ChannelProviderId, ConnectPollHandle>>(
    new Map(),
  );

  // Cancel any in-flight polls when the component using this hook unmounts.
  useEffect(() => {
    const pollers = pollersRef.current;
    return () => {
      pollers.forEach((handle) => handle.cancel());
      pollers.clear();
    };
  }, []);

  return useMutation({
    mutationFn: (provider: ChannelProviderId) =>
      connectChannelProvider(provider),
    onSuccess: (result, provider) => {
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });

      // Replace any existing poll for this provider so repeated Connect clicks
      // don't spawn parallel polling chains racing on the same query keys.
      pollersRef.current.get(provider)?.cancel();
      pollersRef.current.set(
        provider,
        startConnectionPoll({
          provider,
          expiresInSeconds: result.expires_in,
          fetchConnections: () =>
            queryClient.fetchQuery({
              queryKey: channelConnectionsQueryKey,
              queryFn: () => listChannelConnections(),
            }),
          onConnected: () => {
            // Refresh derived provider state exactly once when the bind lands.
            void queryClient.invalidateQueries({
              queryKey: channelProviderQueryKey,
            });
          },
        }),
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
