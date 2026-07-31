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
  updateMCPServerState,
} from "./api";

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
