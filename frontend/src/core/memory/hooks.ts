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

export function useMemory(threadId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory", threadId],
    queryFn: () => loadMemory(threadId!),
    enabled: Boolean(threadId),
  });
  return { memory: data ?? null, isLoading, error };
}

export function useClearMemory(threadId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => {
      if (!threadId) {
        throw new Error("Missing thread id");
      }
      return clearMemory(threadId);
    },
    onSuccess: (memory) => {
      if (threadId) {
        queryClient.setQueryData<UserMemory>(["memory", threadId], memory);
      }
    },
  });
}

export function useDeleteMemoryFact(threadId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (factId: string) => {
      if (!threadId) {
        throw new Error("Missing thread id");
      }
      return deleteMemoryFact(threadId, factId);
    },
    onSuccess: (memory) => {
      if (threadId) {
        queryClient.setQueryData<UserMemory>(["memory", threadId], memory);
      }
    },
  });
}

export function useImportMemory(threadId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (memory: UserMemory) => {
      if (!threadId) {
        throw new Error("Missing thread id");
      }
      return importMemory(threadId, memory);
    },
    onSuccess: (memory) => {
      if (threadId) {
        queryClient.setQueryData<UserMemory>(["memory", threadId], memory);
      }
    },
  });
}

export function useCreateMemoryFact(threadId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: MemoryFactInput) => {
      if (!threadId) {
        throw new Error("Missing thread id");
      }
      return createMemoryFact(threadId, input);
    },
    onSuccess: (memory) => {
      if (threadId) {
        queryClient.setQueryData<UserMemory>(["memory", threadId], memory);
      }
    },
  });
}

export function useUpdateMemoryFact(threadId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      factId,
      input,
    }: {
      factId: string;
      input: MemoryFactPatchInput;
    }) => {
      if (!threadId) {
        throw new Error("Missing thread id");
      }
      return updateMemoryFact(threadId, factId, input);
    },
    onSuccess: (memory) => {
      if (threadId) {
        queryClient.setQueryData<UserMemory>(["memory", threadId], memory);
      }
    },
  });
}
