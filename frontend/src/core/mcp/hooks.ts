import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { loadMCPConfig, loadMCPServerTools, updateMCPConfig } from "./api";

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

export function useMCPServerTools() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["mcpServerTools"],
    queryFn: () => loadMCPServerTools(),
  });
  return { toolsData: data, isLoading, error, refetch };
}

export function useToggleMCPTool() {
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
      const serverConfig = config.mcp_servers[serverName];
      if (!serverConfig) {
        throw new Error(`MCP server ${serverName} not found`);
      }
      const currentDisabled = serverConfig.disabled_tools ?? [];
      const newDisabled = enabled
        ? currentDisabled.filter((t) => t !== toolName)
        : [...new Set([...currentDisabled, toolName])];
      await updateMCPConfig({
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: {
            ...serverConfig,
            disabled_tools: newDisabled,
          },
        },
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}
