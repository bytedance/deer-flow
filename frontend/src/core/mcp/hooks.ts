import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";

import { useAuth } from "@/core/auth/AuthProvider";

import {
  createMCPServers,
  deleteMCPServer,
  loadMCPConfig,
  MCPConfigRequestError,
  updateMCPServer,
  updateMCPServerState,
} from "./api";
import type { MCPScope } from "./api";
import type { MCPServerConfig } from "./types";

export function useMCPConfig(scope: MCPScope = "user") {
  const { user } = useAuth();
  const { data, isLoading, error } = useQuery({
    queryKey: ["mcpConfig", scope, user?.id],
    queryFn: () => loadMCPConfig(scope),
    enabled: !!user && (scope === "user" || user.system_role === "admin"),
    retry: (count, error) =>
      !(error instanceof MCPConfigRequestError) && count < 3,
  });
  return { config: data, isLoading, error };
}

interface EnableMCPServerVariables {
  serverName: string;
  enabled: boolean;
}

export function getEnableMCPServerMutationOptions(
  queryClient: QueryClient,
  scope: MCPScope = "deployment",
) {
  return {
    mutationFn: ({ serverName, enabled }: EnableMCPServerVariables) =>
      updateMCPServerState(serverName, enabled, scope),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["mcpConfig"] }),
        queryClient.invalidateQueries({ queryKey: ["capabilities"] }),
      ]);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  };
}

export function useEnableMCPServer(scope: MCPScope = "user") {
  const queryClient = useQueryClient();
  return useMutation(getEnableMCPServerMutationOptions(queryClient, scope));
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

export function getMCPServerMutationOptions(
  queryClient: QueryClient,
  scope: MCPScope = "deployment",
) {
  return {
    mutationFn: (variables: MCPServerMutationVariables) => {
      switch (variables.operation) {
        case "create":
          return createMCPServers(variables.servers, scope);
        case "update":
          return updateMCPServer(variables.serverName, variables.server, scope);
        case "delete":
          return deleteMCPServer(variables.serverName, scope);
      }
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["mcpConfig"] }),
        queryClient.invalidateQueries({ queryKey: ["capabilities"] }),
      ]);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  };
}

export function useMCPServerMutation(scope: MCPScope = "user") {
  const queryClient = useQueryClient();
  return useMutation(getMCPServerMutationOptions(queryClient, scope));
}
