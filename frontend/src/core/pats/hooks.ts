import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef } from "react";

import { useAuth } from "@/core/auth/AuthProvider";

import {
  createPat,
  listPats,
  MissingSessionIdentityError,
  PatStoreUnavailableError,
  revokePat,
  SessionChangedDuringCreateError,
  StaleSessionIdentityError,
} from "./api";
import type { DeclaredSessionIdentity } from "./api";
import type { CreatePatRequest } from "./types";

/**
 * PAT summaries are per-account — and, within an account, per session
 * generation: replacing the session (sign-in elsewhere, password change)
 * reissues the cookie with a new generation, and the key must follow it so
 * a fence rejection never strands the observer on the errored key.
 */
export const PATS_QUERY_KEY = "pats" as const;

// The placeholder address the query sits at while no complete identity
// exists. It is never fetched (the query is disabled), so it can never hold
// data — it exists only so the observer has a stable key during handoff.
const PENDING_IDENTITY_KEY = [PATS_QUERY_KEY, "pending-identity"] as const;

export function patQueryKey(identity: DeclaredSessionIdentity) {
  return [PATS_QUERY_KEY, identity.userId, identity.generation] as const;
}

/** Prefix covering every generation of one user's PAT list queries. */
export function patQueriesForUser(userId: string | null) {
  return [PATS_QUERY_KEY, userId ?? "anonymous"] as const;
}

/**
 * The complete identity every browser PAT request declares: the
 * authenticated user plus the session generation from /me. Incomplete —
 * user cleared by a failed /me refresh, or no generation yet — means this
 * tab has no fence-able view of who is signed in, and an undeclared request
 * would be admitted by the backend as a non-browser client, reading or
 * mutating whatever account the cookie currently authenticates. Every
 * browser PAT operation is therefore held until the identity is complete.
 */
function useCompleteSessionIdentity(): DeclaredSessionIdentity | null {
  const { user } = useAuth();
  if (!user || user.session_generation == null) return null;
  return { userId: user.id, generation: user.session_generation };
}

/**
 * The backend's identity fence rejected this tab's stale view of who is
 * signed in (another tab switched the shared session). Reconciling is the
 * only correct response: refreshUser converges React state onto the
 * cookie's account — flipping the user id or the session generation, and
 * with it the identity-scoped query key, so the corrected account's data
 * loads under its own key. Suppressing a refetch trigger alone cannot
 * fence remount, reconnect, or invalidation requests.
 */
function useIdentityReconciler() {
  const { refreshUser } = useAuth();
  return function reconcile() {
    void refreshUser?.();
  };
}

export function usePats() {
  const identity = useCompleteSessionIdentity();
  const reconcile = useIdentityReconciler();
  const queryClient = useQueryClient();

  // Drop the previous identity's cached list the moment the complete
  // identity changes — account switch or session replacement — so nothing
  // cached under the old key can resurface if the cookie flips back within
  // the gc window.
  const previousIdentity = useRef<DeclaredSessionIdentity | null>(identity);
  useEffect(() => {
    const previous = previousIdentity.current;
    const unchanged =
      (previous === null && identity === null) ||
      (previous !== null &&
        identity !== null &&
        previous.userId === identity.userId &&
        previous.generation === identity.generation);
    if (unchanged) return;
    if (previous !== null) {
      void queryClient.removeQueries({ queryKey: patQueryKey(previous) });
    }
    previousIdentity.current = identity;
  }, [identity, queryClient]);

  const query = useQuery({
    queryKey: identity ? patQueryKey(identity) : PENDING_IDENTITY_KEY,
    queryFn: () => listPats(identity),
    // No complete identity means no browser PAT request at all — the page
    // renders the reconciling state instead of a list while this holds.
    enabled: identity !== null,
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
    // True while the browser has no complete session identity: queries and
    // mutations are held until /me reconciles.
    reconciling: identity === null,
  };
}

export function useCreatePat() {
  const client = useQueryClient();
  const { user } = useAuth();
  const identity = useCompleteSessionIdentity();
  const reconcile = useIdentityReconciler();
  // The identity as of the most recent commit. The mutationFn closure that
  // starts a mint freezes the initiating identity, but the fence decision
  // at resolution time must read whatever /me has converged onto by then —
  // a render-phase closure would still be the initiating one.
  const identityRef = useRef<DeclaredSessionIdentity | null>(identity);
  useLayoutEffect(() => {
    identityRef.current = identity;
  });
  return useMutation({
    mutationFn: async (request: CreatePatRequest) => {
      if (!identity) {
        // The page disables the controls; this guard enforces the contract:
        // an undeclared browser mint would bind the credential to whatever
        // account the cookie currently authenticates.
        throw new MissingSessionIdentityError();
      }
      const initiating = identity;
      const created = await createPat(request, initiating);
      // The POST passed the fence as the initiating account, so the minted
      // credential is that account's. If a *confirmed* different account now
      // holds this tab, exposing the raw token would present the initiating
      // account's credential inside the successor's settings UI, where it
      // could be copied under the mistaken belief that it belongs to the
      // signed-in user — withhold it. A null identity is only an
      // inconclusive /me refresh (transient network or parsing failure) with
      // the account and cookie potentially unchanged; withholding the
      // resolved raw token on it would permanently destroy the only copy of
      // an active credential, so it is exposed, and the page-level guard
      // clears the result once a different non-null user is confirmed. Only
      // the user id is compared: a same-account session replacement does not
      // reinterpret the result, the credential is that same user's either
      // way.
      const current = identityRef.current;
      if (current != null && current.userId !== initiating.userId) {
        throw new SessionChangedDuringCreateError();
      }
      return created;
    },
    onSuccess: () => {
      // Deliberately NOT returned: TanStack awaits promises returned from
      // onSuccess, which would keep the mutation pending through the list
      // refetch and delay (or, on a hung refetch, strand) the show-once
      // token the caller is waiting on.
      void client.invalidateQueries({
        queryKey: patQueriesForUser(user?.id ?? null),
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
  const identity = useCompleteSessionIdentity();
  const reconcile = useIdentityReconciler();
  return useMutation({
    mutationFn: (patId: string) => {
      if (!identity) {
        // Same contract as creation: no undeclared browser revocation.
        throw new MissingSessionIdentityError();
      }
      return revokePat(patId, identity);
    },
    onSuccess: async () => {
      // Unlike creation, revocation has no show-once result that must be
      // exposed immediately. Keep the mutation pending until active list
      // observers have refreshed so the success UI cannot leave the revoked
      // credential rendered as active.
      await client.invalidateQueries({
        queryKey: patQueriesForUser(user?.id ?? null),
      });
    },
    onError: (error) => {
      if (error instanceof StaleSessionIdentityError) reconcile();
    },
  });
}
