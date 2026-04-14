import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { loadMCPConfig, updateMCPConfig } from "./api";
import type { MCPConfigUpdate } from "./types";

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
      return updateMCPConfig({
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: {
            ...config.mcp_servers[serverName],
            enabled,
          },
        },
      });
    },
    onSuccess: (updatedConfig) => {
      queryClient.setQueryData(["mcpConfig"], updatedConfig);
    },
  });
}

export function useEnableMCPTool() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();

  return useMutation({
    mutationFn: async ({
      serverName,
      toolName,
      enabled,
    }: {
      serverName: string;
      toolName: string;
      enabled: boolean;
    }) => {
      if (!config) {
        throw new Error("MCP config not found");
      }

      const server = config.mcp_servers[serverName];
      if (!server) {
        throw new Error(`MCP server ${serverName} not found`);
      }

      const nextConfig: MCPConfigUpdate = {
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: {
            ...server,
            tools: {
              ...(server.tools ?? {}),
              [toolName]: {
                ...(server.tools?.[toolName] ?? {
                  description: "",
                  discovered: false,
                }),
                enabled,
              },
            },
          },
        },
      };

      return updateMCPConfig(nextConfig);
    },
    onSuccess: (updatedConfig) => {
      queryClient.setQueryData(["mcpConfig"], updatedConfig);
    },
  });
}
