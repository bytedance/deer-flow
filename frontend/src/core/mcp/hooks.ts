import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { loadMCPConfig, updateMCPConfig } from "./api";
import type {
  MCPConfigUpdate,
  MCPServerConfig,
  MCPServerConfigUpdate,
} from "./types";

function toMCPServerConfigUpdate(server: MCPServerConfig): MCPServerConfigUpdate {
  return {
    enabled: server.enabled,
    description: server.description,
    type: server.type,
    command: server.command,
    args: server.args,
    env: server.env,
    url: server.url,
    headers: server.headers,
    oauth: server.oauth,
    tools: Object.fromEntries(
      Object.entries(server.tools ?? {}).map(([toolName, tool]) => [
        toolName,
        { enabled: tool.enabled },
      ]),
    ),
  };
}

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
          ...Object.fromEntries(
            Object.entries(config.mcp_servers).map(([name, server]) => [
              name,
              toMCPServerConfigUpdate(server),
            ]),
          ),
          [serverName]: {
            ...toMCPServerConfigUpdate(config.mcp_servers[serverName]),
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

      const nextServerConfig = toMCPServerConfigUpdate(server);

      const nextConfig: MCPConfigUpdate = {
        mcp_servers: {
          ...Object.fromEntries(
            Object.entries(config.mcp_servers).map(([name, serverConfig]) => [
              name,
              toMCPServerConfigUpdate(serverConfig),
            ]),
          ),
          [serverName]: {
            ...nextServerConfig,
            tools: {
              ...nextServerConfig.tools,
              [toolName]: {
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
