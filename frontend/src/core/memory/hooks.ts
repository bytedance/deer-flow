import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  batchDeleteMemoryFacts,
  batchUpdateMemoryFacts,
  clearMemory,
  createMemoryFact,
  deleteMemoryFact,
  importMemory,
  loadMemory,
  updateMemoryFact,
} from "./api";
import type {
  BatchDeleteInput,
  BatchUpdateInput,
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "./types";

export function useMemory() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory"],
    queryFn: () => loadMemory(),
  });
  return { memory: data ?? null, isLoading, error };
}

export function useClearMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => clearMemory(),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useDeleteMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (factId: string) => deleteMemoryFact(factId),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useImportMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (memory: UserMemory) => importMemory(memory),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useCreateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: MemoryFactInput) => createMemoryFact(input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useUpdateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      factId,
      input,
    }: {
      factId: string;
      input: MemoryFactPatchInput;
    }) => updateMemoryFact(factId, input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });

export function useBatchDeleteMemoryFacts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: BatchDeleteInput) => batchDeleteMemoryFacts(input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

export function useBatchUpdateMemoryFacts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: BatchUpdateInput) => batchUpdateMemoryFacts(input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}
