import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createPat, revokePat, listPats } from "./api";
import type { CreatePatRequest } from "./types";

export const PATS_QUERY_KEY = ["pats"] as const;

export function usePats() {
  const query = useQuery({
    queryKey: PATS_QUERY_KEY,
    queryFn: listPats,
    // A 503 (memory backend, no PAT store) is a legitimate deployment state,
    // not a transient failure worth retrying.
    retry: false,
  });
  return {
    pats: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}

export function useCreatePat() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: CreatePatRequest) => createPat(request),
    onSuccess: () => client.invalidateQueries({ queryKey: PATS_QUERY_KEY }),
    // The mutation result carries the show-once token; once the observer is
    // done with it there is no reason for the MutationCache to keep a copy
    // for the default 5-minute gc window.
    gcTime: 0,
  });
}

export function useRevokePat() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (patId: string) => revokePat(patId),
    onSuccess: () => client.invalidateQueries({ queryKey: PATS_QUERY_KEY }),
  });
}
