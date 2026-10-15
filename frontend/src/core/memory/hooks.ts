import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

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
 * Install a confirmed memory write in the shared `["memory"]` cache.
 *
 * Every memory operation shares one query key, so a `loadMemory` that started
 * before the write can still land afterwards and put the old document back:
 * deleted facts reappear and imported facts disappear. Cancelling the in-flight
 * query first is what makes the mutation response the last writer; reads
 * started after this point still refresh normally.
 */
async function commitMemory(queryClient: QueryClient, memory: UserMemory) {
  await queryClient.cancelQueries({ queryKey: ["memory"] });
  queryClient.setQueryData<UserMemory>(["memory"], memory);
}

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
    async onSuccess(memory) {
      await commitMemory(queryClient, memory);
    },
  });
}

export function useDeleteMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (factId: string) => deleteMemoryFact(factId),
    async onSuccess(memory) {
      await commitMemory(queryClient, memory);
    },
  });
}

export function useImportMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (memory: UserMemory) => importMemory(memory),
    async onSuccess(memory) {
      await commitMemory(queryClient, memory);
    },
  });
}

export function useCreateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: MemoryFactInput) => createMemoryFact(input),
    async onSuccess(memory) {
      await commitMemory(queryClient, memory);
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
    async onSuccess(memory) {
      await commitMemory(queryClient, memory);
    },
  });
}
