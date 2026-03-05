import { useQuery } from "@tanstack/react-query";

import { loadAgentContext, type AgentContextParams } from "./api";

export function useAgentContext({ modelName, subagentEnabled }: AgentContextParams) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agentContext", modelName ?? null, subagentEnabled ?? null],
    queryFn: () => loadAgentContext({ modelName, subagentEnabled }),
    staleTime: 5 * 60 * 1000, // 5 minutes — avoid refetching on every mount/focus
  });
  return { context: data, isLoading, error };
}
