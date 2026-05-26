import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearMemory,
  createDomainFact,
  createMemoryFact,
  deleteMemoryFact,
  exportDomainMemory,
  exportSessionMemory,
  importDomainFacts,
  importMemory,
  importSessionMemory,
  loadAuditLogs,
  loadMemory,
  loadSessionMemory,
  searchDomainMemory,
  updateMemoryFact,
} from "./api";
import type {
  AuditEntry,
  DomainFact,
  DomainFactCreateInput,
  MemoryFactInput,
  MemoryFactPatchInput,
  SessionMemory,
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
}

// ---------------------------------------------------------------------------
// Session Memory
// ---------------------------------------------------------------------------

export function useSessionMemory(threadId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["session-memory", threadId],
    queryFn: () => loadSessionMemory(threadId!),
    enabled: !!threadId,
  });
  return { sessionMemory: data ?? null, isLoading, error };
}

export function useExportSessionMemory() {
  return useMutation({
    mutationFn: (threadId: string) => exportSessionMemory(threadId),
  });
}

export function useImportSessionMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      threadId,
      facts,
    }: {
      threadId: string;
      facts: SessionMemory["facts"];
    }): Promise<SessionMemory> => importSessionMemory(threadId, facts),
    onSuccess: (data: SessionMemory) => {
      queryClient.setQueryData<SessionMemory>(
        ["session-memory", data.thread_id],
        data,
      );
    },
  });
}

// ---------------------------------------------------------------------------
// Domain Memory
// ---------------------------------------------------------------------------

export function useDomainMemory(
  query: string,
  options?: { domain?: string; entityId?: string; topK?: number },
) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["domain-memory", query, options?.domain, options?.entityId, options?.topK],
    queryFn: () => searchDomainMemory(query, options),
    enabled: query.trim().length > 0,
  });
  return { domainFacts: data ?? [], isLoading, error };
}

export function useCreateDomainFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: DomainFactCreateInput) => createDomainFact(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["domain-memory"] });
    },
  });
}

export function useExportDomainMemory() {
  return useMutation({
    mutationFn: (options?: { domain?: string; entityId?: string }) =>
      exportDomainMemory(options),
  });
}

export function useImportDomainFacts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (facts: DomainFactCreateInput[]) => importDomainFacts(facts),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["domain-memory"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Audit Logs
// ---------------------------------------------------------------------------

export function useAuditLogs(
  options?: { userId?: string; action?: string; layer?: string; limit?: number },
) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory-audit", options?.userId, options?.action, options?.layer, options?.limit],
    queryFn: () => loadAuditLogs(options),
  });
  return { auditLogs: data ?? [], isLoading, error };
}
