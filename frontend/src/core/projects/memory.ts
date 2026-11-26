import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { PROJECTS_QUERY_KEY } from "./api";

export type ProjectMemory = {
  enabled: boolean;
  max_facts: number;
  facts: {
    id: string;
    content: string;
    source_thread_id: string;
    created_at: string;
  }[];
};

async function memoryRequest<T>(
  projectId: string,
  suffix = "",
  init?: RequestInit,
): Promise<T> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/projects/${encodeURIComponent(projectId)}/memory${suffix}`,
    init,
  );
  if (!response.ok) throw new Error("Project memory request failed");
  return (await response.json()) as T;
}

export function useProjectMemory(projectId: string) {
  return useQuery({
    queryKey: [...PROJECTS_QUERY_KEY, "memory", projectId],
    queryFn: ({ signal }) =>
      memoryRequest<ProjectMemory>(projectId, "", { signal }),
    enabled: !isStaticWebsiteOnly(),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });
}

type MemoryAction =
  | { kind: "toggle"; enabled: boolean }
  | { kind: "delete"; factId: string }
  | { kind: "promote"; factId: string; instructions: string };

export function useProjectMemoryAction(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationKey: [...PROJECTS_QUERY_KEY, "memory-action", projectId],
    mutationFn: async (action: MemoryAction) => {
      if (action.kind === "promote") {
        return memoryRequest<{ memory: ProjectMemory; instructions: string }>(
          projectId,
          `/${encodeURIComponent(action.factId)}/promote`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_instructions: action.instructions,
            }),
          },
        );
      }
      const memory = await memoryRequest<ProjectMemory>(
        projectId,
        action.kind === "delete" ? `/${encodeURIComponent(action.factId)}` : "",
        action.kind === "delete"
          ? { method: "DELETE" }
          : {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ enabled: action.enabled }),
            },
      );
      return { memory };
    },
    onSuccess: async (result) => {
      client.setQueryData(
        [...PROJECTS_QUERY_KEY, "memory", projectId],
        result.memory,
      );
      await client.invalidateQueries({
        queryKey: [...PROJECTS_QUERY_KEY, "detail", projectId],
      });
    },
  });
}

export function useProjectMemoryMutationPending(projectId: string) {
  return (
    useIsMutating({
      mutationKey: [...PROJECTS_QUERY_KEY, "memory-action", projectId],
    }) > 0
  );
}
