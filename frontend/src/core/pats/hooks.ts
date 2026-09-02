import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useAuth } from "@/core/auth/AuthProvider";

import {
  createPat,
  listPats,
  PatStoreUnavailableError,
  revokePat,
  StaleSessionIdentityError,
} from "./api";
import type { SessionIdentity } from "./api";
import type { CreatePatRequest } from "./types";

/**
 * PAT summaries are per-account data: the key carries the authenticated
 * user's id so signing out and back in as a different user within the cache
 * retention window can never surface the previous account's tokens.
 */
export function patQueryKey(userId: string | null) {
  return ["pats", userId ?? "anonymous"] as const;
}

function useSessionIdentity(): SessionIdentity | null {
  const { user } = useAuth();
  if (!user) return null;
  return { userId: user.id, generation: user.session_generation ?? null };
}

/**
 * The backend's identity fence rejected this tab's stale view of who is
 * signed in (another tab switched the shared session). Reconciling is the
 * only correct response: refreshUser converges React state onto the
 * cookie's account, which changes the identity-scoped query key, so the
 * corrected account's data loads under its own key. Suppressing a refetch
 * trigger alone cannot fence remount, reconnect, or invalidation requests.
 */
function useIdentityReconciler() {
  const { refreshUser } = useAuth();
  return function reconcile() {
    void refreshUser?.();
  };
}

export function usePats() {
  const { user } = useAuth();
  const identity = useSessionIdentity();
  const reconcile = useIdentityReconciler();
  const queryClient = useQueryClient();
  const userId = user?.id ?? null;

  // A cross-tab account switch replaces the session cookie immediately,
  // while this tab's React auth state only catches up after AuthProvider's
  // throttled visibility refresh. Any fetch TanStack fires in that window
  // carries the stale identity's declaration, which the backend fence
  // rejects before any data crosses the boundary — and the previous
  // identity's cached list is dropped on change so it can never resurface
  // if the cookie flips back within the gc window.
  const previousUserId = useRef<string | null>(userId);
  useEffect(() => {
    if (previousUserId.current === userId) return;
    void queryClient.removeQueries({
      queryKey: patQueryKey(previousUserId.current),
    });
    previousUserId.current = userId;
  }, [userId, queryClient]);

  const query = useQuery({
    queryKey: patQueryKey(userId),
    queryFn: () => listPats(identity),
    refetchOnWindowFocus: false,
    // A 503 (memory backend, no PAT store) is a legitimate deployment state,
    // not a transient failure worth retrying — everything else (network
    // blips, 5xx) retries like the skills hook (count < 3). A bare predicate
    // would replace TanStack's numeric default with "retry forever", pinning
    // the page in the loading state and never surfacing the error. A stale
    // identity also must not retry: the declaration cannot become correct
    // until the reconciler converges the auth state.
    retry: (count, error) =>
      !(error instanceof PatStoreUnavailableError) &&
      !(error instanceof StaleSessionIdentityError) &&
      count < 3,
  });

  // Reconcile exactly once per stale-identity rejection: the refresh flips
  // the auth state (and with it the query key), which is what actually
  // resolves the situation — retrying the same declaration never would.
  const reconciled = useRef(false);
  useEffect(() => {
    const stale = query.error instanceof StaleSessionIdentityError;
    if (stale && !reconciled.current) {
      reconciled.current = true;
      reconcile();
    }
    if (!stale) {
      reconciled.current = false;
    }
  }, [query.error, reconcile]);
  return {
    pats: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}

export function useCreatePat() {
  const client = useQueryClient();
  const { user } = useAuth();
  const identity = useSessionIdentity();
  const reconcile = useIdentityReconciler();
  return useMutation({
    mutationFn: (request: CreatePatRequest) => createPat(request, identity),
    onSuccess: () => {
      // Deliberately NOT returned: TanStack awaits promises returned from
      // onSuccess, which would keep the mutation pending through the list
      // refetch and delay (or, on a hung refetch, strand) the show-once
      // token the caller is waiting on.
      void client.invalidateQueries({
        queryKey: patQueryKey(user?.id ?? null),
      });
    },
    onError: (error) => {
      if (error instanceof StaleSessionIdentityError) reconcile();
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
  const identity = useSessionIdentity();
  const reconcile = useIdentityReconciler();
  return useMutation({
    mutationFn: (patId: string) => revokePat(patId, identity),
    onSuccess: async () => {
      // Unlike creation, revocation has no show-once result that must be
      // exposed immediately. Keep the mutation pending until active list
      // observers have refreshed so the success UI cannot leave the revoked
      // credential rendered as active.
      await client.invalidateQueries({
        queryKey: patQueryKey(user?.id ?? null),
      });
    },
    onError: (error) => {
      if (error instanceof StaleSessionIdentityError) reconcile();
    },
  });
}
