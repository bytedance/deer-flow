import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";

import {
  createMCPServers,
  deleteMCPServer,
  loadMCPConfig,
  MCPConfigRequestError,
  updateMCPServer,
  updateMCPServerState,
} from "./api";
import type { MCPServerConfig } from "./types";

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

export type MCPServerMutationVariables =
  | {
      operation: "create";
      servers: Record<string, MCPServerConfig>;
    }
  | {
      operation: "update";
      serverName: string;
      server: MCPServerConfig;
    }
  | {
      operation: "delete";
      serverName: string;
    };

export function getMCPServerMutationOptions(queryClient: QueryClient) {
  return {
    mutationFn: (variables: MCPServerMutationVariables) => {
      switch (variables.operation) {
        case "create":
          return createMCPServers(variables.servers);
        case "update":
          return updateMCPServer(variables.serverName, variables.server);
        case "delete":
          return deleteMCPServer(variables.serverName);
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mcpConfig"] }),
    onError: (error: Error) => {
      toast.error(error.message);
    },
  };
}

export function useMCPServerMutation() {
  const queryClient = useQueryClient();
  return useMutation(getMCPServerMutationOptions(queryClient));
}
