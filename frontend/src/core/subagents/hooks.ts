import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createManagedSubagent,
  deleteManagedSubagent,
  listSubagents,
  updateManagedSubagent,
} from "./api";
import type {
  CreateManagedSubagentRequest,
  UpdateManagedSubagentRequest,
} from "./types";

export const SUBAGENTS_QUERY_KEY = ["subagents"] as const;

export function useSubagents() {
  const query = useQuery({
    queryKey: SUBAGENTS_QUERY_KEY,
    queryFn: listSubagents,
  });
  return {
    subagents: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}

export function useCreateManagedSubagent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateManagedSubagentRequest) =>
      createManagedSubagent(request),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: SUBAGENTS_QUERY_KEY }),
  });
}

export function useUpdateManagedSubagent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      request,
    }: {
      name: string;
      request: UpdateManagedSubagentRequest;
    }) => updateManagedSubagent(name, request),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: SUBAGENTS_QUERY_KEY }),
  });
}

export function useDeleteManagedSubagent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: deleteManagedSubagent,
    onSuccess: () =>
      client.invalidateQueries({ queryKey: SUBAGENTS_QUERY_KEY }),
  });
}
