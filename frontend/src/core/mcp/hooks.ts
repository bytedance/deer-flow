import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";

import {
  loadMCPConfig,
  MCPConfigRequestError,
  updateMCPConfig,
  updateMCPServerState,
} from "./api";
import type { MCPConfig } from "./types";

export function useMCPConfig() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["mcpConfig"],
    queryFn: () => loadMCPConfig(),
    retry: (count, error) =>
      !(error instanceof MCPConfigRequestError) && count < 3,
  });
  return { config: data, isLoading, error };
}

interface EnableMCPServerVariables {
  serverName: string;
  enabled: boolean;
}

export function getEnableMCPServerMutationOptions(queryClient: QueryClient) {
  return {
    mutationFn: ({ serverName, enabled }: EnableMCPServerVariables) =>
      updateMCPServerState(serverName, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mcpConfig"] }),
    onError: (error: Error) => {
      toast.error(error.message);
    },
  };
}

export function useEnableMCPServer() {
  const queryClient = useQueryClient();
  return useMutation(getEnableMCPServerMutationOptions(queryClient));
}

export function getUpdateMCPConfigMutationOptions(queryClient: QueryClient) {
  return {
    mutationFn: (config: MCPConfig) => updateMCPConfig(config),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mcpConfig"] }),
    onError: (error: Error) => {
      toast.error(error.message);
    },
  };
}

/**
 * Write the whole `mcpServers` map.
 *
 * `PUT /api/mcp/config` replaces that key with what it receives, so callers
 * must send the complete map — adding is a merge into the current servers,
 * removing is omitting one from them. Values masked as `***` by the GET
 * response round-trip safely; the Gateway restores the real secrets from disk.
 */
export function useUpdateMCPConfig() {
  const queryClient = useQueryClient();
  return useMutation(getUpdateMCPConfigMutationOptions(queryClient));
}
