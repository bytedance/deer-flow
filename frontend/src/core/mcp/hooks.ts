import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listOAuthPresets,
  loadMCPConfig,
  startOAuthFlow,
  testMCPServer,
  updateMCPConfig,
} from "./api";
import type { MCPServerConfig } from "./types";

export function useMCPConfig() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["mcpConfig"],
    queryFn: () => loadMCPConfig(),
  });
  return { config: data, isLoading, error };
}

export function useEnableMCPServer() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async ({
      serverName,
      enabled,
    }: {
      serverName: string;
      enabled: boolean;
    }) => {
      if (!config) {
        throw new Error("MCP config not found");
      }
      if (!config.mcp_servers[serverName]) {
        throw new Error(`MCP server ${serverName} not found`);
      }
      await updateMCPConfig({
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: {
            ...config.mcp_servers[serverName],
            enabled,
          },
        },
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}

export function useAddMCPServer() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async ({
      serverName,
      serverConfig,
    }: {
      serverName: string;
      serverConfig: MCPServerConfig;
    }) => {
      if (!config) {
        throw new Error("MCP config not found");
      }
      await updateMCPConfig({
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: serverConfig,
        },
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}

export function useOAuthPresets() {
  return useQuery({
    queryKey: ["mcpOAuthPresets"],
    queryFn: listOAuthPresets,
    staleTime: 60_000,
  });
}

export function useStartOAuth() {
  return useMutation({
    mutationFn: (presetId: string) => startOAuthFlow(presetId),
  });
}

export function useTestMCPServer() {
  return useMutation({
    mutationFn: (serverName: string) => testMCPServer(serverName),
  });
}

export function useInvalidateMCPConfig() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
}

export function useRemoveMCPServer() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async ({ serverName }: { serverName: string }) => {
      if (!config) {
        throw new Error("MCP config not found");
      }
      const nextServers = { ...config.mcp_servers };
      delete nextServers[serverName];
      await updateMCPConfig({ mcp_servers: nextServers });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}
