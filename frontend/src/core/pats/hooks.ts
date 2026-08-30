import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/core/auth/AuthProvider";

import {
  createPat,
  listPats,
  PatStoreUnavailableError,
  revokePat,
} from "./api";
import type { CreatePatRequest } from "./types";

/**
 * PAT summaries are per-account data: the key carries the authenticated
 * user's id so signing out and back in as a different user within the cache
 * retention window can never surface the previous account's tokens.
 */
export function patQueryKey(userId: string | null) {
  return ["pats", userId ?? "anonymous"] as const;
}

export function usePats() {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: patQueryKey(user?.id ?? null),
    queryFn: listPats,
    // A 503 (memory backend, no PAT store) is a legitimate deployment state,
    // not a transient failure worth retrying — everything else (network
    // blips, 5xx) retries like the skills hook (count < 3). A bare predicate
    // would replace TanStack's numeric default with "retry forever", pinning
    // the page in the loading state and never surfacing the error.
    retry: (count, error) =>
      !(error instanceof PatStoreUnavailableError) && count < 3,
  });
  return {
    pats: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}

export function useCreatePat() {
  const client = useQueryClient();
  const { user } = useAuth();
  return useMutation({
    mutationFn: (request: CreatePatRequest) => createPat(request),
    onSuccess: () => {
      // Deliberately NOT returned: TanStack awaits promises returned from
      // onSuccess, which would keep the mutation pending through the list
      // refetch and delay (or, on a hung refetch, strand) the show-once
      // token the caller is waiting on.
      void client.invalidateQueries({
        queryKey: patQueryKey(user?.id ?? null),
      });
    },
    // The mutation result carries the show-once token; once the observer is
    // done with it there is no reason for the MutationCache to keep a copy
    // for the default 5-minute gc window.
    gcTime: 0,
  });
}

export function useRevokePat() {
  const client = useQueryClient();
  const { user } = useAuth();
  return useMutation({
    mutationFn: (patId: string) => revokePat(patId),
    onSuccess: async () => {
      // Unlike creation, revocation has no show-once result that must be
      // exposed immediately. Keep the mutation pending until active list
      // observers have refreshed so the success UI cannot leave the revoked
      // credential rendered as active.
      await client.invalidateQueries({
        queryKey: patQueryKey(user?.id ?? null),
      });
    },
  });
}
