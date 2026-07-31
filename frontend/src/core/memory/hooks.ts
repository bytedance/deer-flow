import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearMemory,
  createMemoryFact,
  deleteMemoryFact,
  importMemory,
  loadMemory,
  updateMemoryFact,
} from "./api";
import type {
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "./types";

/**
 * Memory queries are keyed by fact bucket: `["memory", agentName]`, where a
 * null agentName selects the default bucket. Summaries are user-global and
 * therefore identical across buckets, but facts are per-agent, so every
 * bucket keeps its own cache entry. Mutations carry the agentName they
 * operated on and refresh exactly that cache entry, so switching the
 * selection while a mutation is in flight cannot write the response into the
 * wrong bucket's cache.
 */
export function useMemory(agentName: string | null = null) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory", agentName],
    queryFn: () => loadMemory(agentName),
  });
  return { memory: data ?? null, isLoading, error };
}

export function useClearMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (agentName: string | null) => clearMemory(agentName),
    onSuccess: (memory, agentName) => {
      queryClient.setQueryData<UserMemory>(["memory", agentName], memory);
      if (agentName === null) {
        // An unscoped clear wipes every agent's facts and the shared
        // summaries, so all bucket caches are stale.
        void queryClient.invalidateQueries({ queryKey: ["memory"] });
      }
    },
  });
}

export function useDeleteMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      factId,
      agentName,
    }: {
      factId: string;
      agentName: string | null;
    }) => deleteMemoryFact(factId, agentName),
    onSuccess: (memory, { agentName }) => {
      queryClient.setQueryData<UserMemory>(["memory", agentName], memory);
    },
  });
}

export function useImportMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      memory,
      agentName,
    }: {
      memory: UserMemory;
      agentName: string | null;
    }) => importMemory(memory, agentName),
    onSuccess: (memory, { agentName }) => {
      queryClient.setQueryData<UserMemory>(["memory", agentName], memory);
      // An import also replaces the user-global summaries shared by every
      // bucket, so refresh the other buckets' caches too.
      void queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
  });
}

export function useCreateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      input,
      agentName,
    }: {
      input: MemoryFactInput;
      agentName: string | null;
    }) => createMemoryFact(input, agentName),
    onSuccess: (memory, { agentName }) => {
      queryClient.setQueryData<UserMemory>(["memory", agentName], memory);
    },
  });
}

export function useUpdateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      factId,
      input,
      agentName,
    }: {
      factId: string;
      input: MemoryFactPatchInput;
      agentName: string | null;
    }) => updateMemoryFact(factId, input, agentName),
    onSuccess: (memory, { agentName }) => {
      queryClient.setQueryData<UserMemory>(["memory", agentName], memory);
    },
  });
}
