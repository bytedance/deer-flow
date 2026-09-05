import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { type PropsWithChildren } from "react";

const fetchMock = rs.hoisted(() => rs.fn());
// Mutable on purpose: the identity-switch regression needs to change the
// authenticated user between renders, which the static useAuth mock can't.
const authMock = rs.hoisted(() => ({
  user: null as {
    id: string;
    session_generation?: number | null;
  } | null,
}));
const refreshUserMock = rs.hoisted(() => rs.fn());

rs.mock("@/core/api/fetcher", () => ({
  fetch: fetchMock,
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: authMock.user, refreshUser: refreshUserMock }),
}));

import {
  MissingSessionIdentityError,
  PatStoreUnavailableError,
  SessionChangedDuringCreateError,
  StaleSessionIdentityError,
} from "@/core/pats/api";
import {
  patQueriesForUser,
  patQueryKey,
  RECONCILE_RETRY_INTERVAL_MS,
  useCreatePat,
  usePats,
  useRevokePat,
} from "@/core/pats/hooks";
import type { PatSummary } from "@/core/pats/types";

function createWrapper(queryClient: QueryClient) {
  return function QueryWrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

function summary(id: string): PatSummary {
  return {
    id,
    name: `token ${id}`,
    scopes: ["threads:read"],
    expires_at: null,
    last_used_at: null,
    created_at: "2026-01-01T00:00:00Z",
    revoked_at: null,
  };
}

function staleIdentityResponse(): Response {
  return new Response(
    JSON.stringify({
      detail: "Session identity changed — refresh the page and retry",
    }),
    { status: 409, headers: { "Content-Type": "application/json" } },
  );
}

function identity(userId: string, generation: number) {
  return { userId, generation } as const;
}

describe("useRevokePat", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    refreshUserMock.mockReset();
    authMock.user = { id: "test-user", session_generation: 1756700000 };
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps revocation pending until the refreshed token list settles", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    let finishRefresh!: () => void;
    const refresh = new Promise<void>((resolve) => {
      finishRefresh = resolve;
    });
    const invalidateQueries = rs
      .spyOn(queryClient, "invalidateQueries")
      .mockReturnValue(refresh);

    const { result } = renderHook(() => useRevokePat(), {
      wrapper: createWrapper(queryClient),
    });
    let settled = false;
    let revokePromise!: Promise<void>;

    act(() => {
      revokePromise = result.current.mutateAsync("pat-1").then(() => {
        settled = true;
      });
    });

    await waitFor(() => {
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: patQueriesForUser("test-user"),
      });
    });
    expect(settled).toBe(false);

    await act(async () => {
      finishRefresh();
      await revokePromise;
    });
    expect(settled).toBe(true);
  });

  it("refuses to revoke while the session identity is incomplete", async () => {
    // A cleared user (failed /me refresh) must never issue an undeclared
    // DELETE: the backend admits undeclared requests as non-browser clients
    // and would revoke the cookie's current account unfenced.
    authMock.user = null;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useRevokePat(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await expect(result.current.mutateAsync("pat-1")).rejects.toBeInstanceOf(
        MissingSessionIdentityError,
      );
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("useCreatePat", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    refreshUserMock.mockReset();
    authMock.user = { id: "user-a", session_generation: 1756700000 };
  });

  afterEach(() => {
    cleanup();
  });

  it("refuses to mint while the session identity is incomplete", async () => {
    // Same fence contract as revocation: a browser mint without a complete
    // declaration would bind the new credential to whatever account the
    // cookie currently authenticates.
    authMock.user = { id: "user-a" };
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useCreatePat(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await expect(
        result.current.mutateAsync({
          name: "ci",
          scopes: ["threads:read"],
          expires_in_days: null,
        }),
      ).rejects.toBeInstanceOf(MissingSessionIdentityError);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("withholds the show-once token when the account changes mid-mint", async () => {
    // The POST passed the fence as user-a, but another tab replaced the
    // shared cookie and this tab's /me refresh already flipped the React
    // user to user-b before the response resolved. The raw token is
    // user-a's credential; returning it would render it inside user-b's
    // settings UI where it could be copied as user-b's own.
    let resolveCreate!: (value: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveCreate = resolve;
        }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result, rerender } = renderHook(() => useCreatePat(), {
      wrapper: createWrapper(queryClient),
    });

    const pending = result.current.mutateAsync({
      name: "ci",
      scopes: ["threads:read"],
      expires_in_days: null,
    });
    // The mint must already be in flight (fetch issued with user-a's
    // declaration) before the account flips, and the hook must re-render
    // so the latest-identity ref sees the successor.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => {
      authMock.user = { id: "user-b", session_generation: 1756800000 };
    });
    rerender();
    await act(async () => {
      resolveCreate(
        Response.json({
          id: "pat-1",
          name: "ci",
          scopes: ["threads:read"],
          expires_at: null,
          created_at: "2026-01-01T00:00:00Z",
          token: "dcp_raw_show_once_value",
        }),
      );
      await expect(pending).rejects.toBeInstanceOf(
        SessionChangedDuringCreateError,
      );
    });
    expect(result.current.data).toBeUndefined();
  });

  it("still exposes the token when only the same user's generation advanced", async () => {
    // A same-account session replacement does not reinterpret the result:
    // the minted credential belongs to the same user either way, so the
    // generation component of the identity is deliberately not compared.
    let resolveCreate!: (value: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveCreate = resolve;
        }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result, rerender } = renderHook(() => useCreatePat(), {
      wrapper: createWrapper(queryClient),
    });

    const pending = result.current.mutateAsync({
      name: "ci",
      scopes: ["threads:read"],
      expires_in_days: null,
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => {
      authMock.user = { id: "user-a", session_generation: 1756900000 };
    });
    rerender();
    await act(async () => {
      resolveCreate(
        Response.json({
          id: "pat-1",
          name: "ci",
          scopes: ["threads:read"],
          expires_at: null,
          created_at: "2026-01-01T00:00:00Z",
          token: "dcp_raw_show_once_value",
        }),
      );
      const created = await pending;
      expect(created.token).toBe("dcp_raw_show_once_value");
    });
    await waitFor(() => {
      expect(result.current.data?.token).toBe("dcp_raw_show_once_value");
    });
  });

  it("still exposes the token when the refresh is inconclusive mid-mint", async () => {
    // /me can fail transiently while the POST is in flight; a null identity
    // is "unknown", not a confirmed handoff — withholding the resolved raw
    // token would permanently destroy the only copy of an active
    // credential. The page-level guard clears the result only after a
    // different non-null user is confirmed.
    let resolveCreate!: (value: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveCreate = resolve;
        }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result, rerender } = renderHook(() => useCreatePat(), {
      wrapper: createWrapper(queryClient),
    });

    const pending = result.current.mutateAsync({
      name: "ci",
      scopes: ["threads:read"],
      expires_in_days: null,
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => {
      authMock.user = null;
    });
    rerender();
    await act(async () => {
      resolveCreate(
        Response.json({
          id: "pat-1",
          name: "ci",
          scopes: ["threads:read"],
          expires_at: null,
          created_at: "2026-01-01T00:00:00Z",
          token: "dcp_raw_show_once_value",
        }),
      );
      const created = await pending;
      expect(created.token).toBe("dcp_raw_show_once_value");
    });
  });
});

describe("usePats", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    refreshUserMock.mockReset();
    authMock.user = { id: "user-a", session_generation: 1756700000 };
  });

  afterEach(() => {
    cleanup();
  });

  it("does not refetch on window focus", async () => {
    // A cross-tab account switch replaces the session cookie immediately,
    // while this tab's React auth state only catches up after the throttled
    // visibility refresh. A focus refetch would fetch the new account's list
    // and cache it under the old identity's key, so the query must not
    // subscribe to focus at all.
    fetchMock.mockResolvedValue(Response.json([summary("pat-a")]));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => usePats(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.pats).toHaveLength(1);
    });
    fetchMock.mockClear();

    act(() => {
      // v5's focus manager subscribes to window "visibilitychange", not
      // "focus" — dispatching the event the manager actually listens to.
      window.dispatchEvent(new Event("visibilitychange"));
    });
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("drops the previous identity's cached list when the user changes", async () => {
    fetchMock
      .mockResolvedValueOnce(Response.json([summary("pat-a")]))
      .mockResolvedValueOnce(Response.json([summary("pat-b")]));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result, rerender } = renderHook(() => usePats(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.pats.map((pat) => pat.id)).toEqual(["pat-a"]);
    });

    act(() => {
      authMock.user = { id: "user-b", session_generation: 1756800000 };
    });
    rerender();

    await waitFor(() => {
      expect(result.current.pats.map((pat) => pat.id)).toEqual(["pat-b"]);
    });
    expect(
      queryClient.getQueryData(patQueryKey(identity("user-a", 1756700000))),
    ).toBeUndefined();
    expect(
      queryClient.getQueryData(patQueryKey(identity("user-b", 1756800000))),
    ).toEqual([summary("pat-b")]);
  });

  it("declares the session identity on list requests once /me provided a generation", async () => {
    authMock.user = { id: "user-a", session_generation: 1756700000 };
    fetchMock.mockResolvedValue(Response.json([summary("pat-a")]));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => usePats(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.pats).toHaveLength(1);
    });
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-DF-Session"]).toBe(
      "user-a:1756700000",
    );
  });

  it("holds list requests while the session identity is incomplete", async () => {
    // The fence admits undeclared requests on purpose (curl flows), so the
    // browser must never be the one to send them: with the user cleared by a
    // failed /me refresh — or /me not having provided a generation yet — no
    // list request may leave, and the hook reports the reconciling state the
    // page renders instead of an empty list.
    for (const user of [null, { id: "user-a" }] as const) {
      fetchMock.mockReset();
      authMock.user = user as { id: string } | null;
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const { result } = renderHook(() => usePats(), {
        wrapper: createWrapper(queryClient),
      });

      await new Promise((resolve) => setTimeout(resolve, 50));

      expect(fetchMock).not.toHaveBeenCalled();
      expect(result.current.pats).toEqual([]);
      expect(result.current.reconciling).toBe(true);
      cleanup();
    }
  });

  it("retries a non-canonical 503 instead of pinning the store banner", async () => {
    // Only deps.py's canonical "Personal access tokens require a configured
    // database" means the memory backend. A proxy or load balancer 503 with
    // any other body is transient: it must walk the retry path and recover
    // when the next attempt succeeds — not suppress retries and hide token
    // creation behind the database-required banner.
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Service Temporarily Unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(Response.json([summary("pat-a")]));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => usePats(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(
      () => {
        expect(result.current.pats.map((pat) => pat.id)).toEqual(["pat-a"]);
      },
      // TanStack's first retry delay is 1s; the default waitFor timeout
      // would race it.
      { timeout: 5000 },
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.error).toBeNull();
  });

  it("treats only the canonical store-unavailable detail as permanent", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Personal access tokens require a configured database",
        }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => usePats(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.error).toBeInstanceOf(PatStoreUnavailableError);
    });
    // Permanent deployment state: exactly one request, no retry walk.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("recovers on the new generation's key after the fence rejects a replaced session", async () => {
    // Password change: same user, reissued session cookie, new generation.
    // The first list request carries the old generation and is fenced with
    // 409; reconciliation refreshes /me, and the corrected generation must
    // flip the query key — otherwise the observer stays on the errored
    // query and the page is stuck on "Session identity changed" forever.
    authMock.user = { id: "user-a", session_generation: 1756700000 };
    fetchMock
      .mockResolvedValueOnce(staleIdentityResponse())
      .mockResolvedValueOnce(Response.json([summary("pat-a")]));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result, rerender } = renderHook(() => usePats(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.error).toBeInstanceOf(StaleSessionIdentityError);
    });
    await waitFor(() => {
      expect(refreshUserMock).toHaveBeenCalledTimes(1);
    });

    // What the reconciled /me produces: the same user under generation 2.
    act(() => {
      authMock.user = { id: "user-a", session_generation: 1756800000 };
    });
    rerender();

    await waitFor(() => {
      expect(result.current.pats.map((pat) => pat.id)).toEqual(["pat-a"]);
    });
    expect(result.current.error).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const second = fetchMock.mock.calls[1]![1] as RequestInit;
    expect((second.headers as Record<string, string>)["X-DF-Session"]).toBe(
      "user-a:1756800000",
    );
    // The rejected generation's entry cannot resurface inside the gc window.
    expect(
      queryClient.getQueryData(patQueryKey(identity("user-a", 1756700000))),
    ).toBeUndefined();
  });

  it("retries reconciliation after an inconclusive refresh", async () => {
    // A stale-identity 409 triggers reconciliation; the /me refresh then
    // fails transiently and clears the user. With the identity gone, the
    // auth layer skips visibility refreshes and this hook's query is
    // disabled — without a steady retry the page sits in the reconciling
    // state until a hard reload.
    rs.useFakeTimers();
    try {
      authMock.user = { id: "user-a", session_generation: 1756700000 };
      fetchMock.mockResolvedValue(staleIdentityResponse());
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const { result, rerender } = renderHook(() => usePats(), {
        wrapper: createWrapper(queryClient),
      });

      await act(async () => {
        await rs.advanceTimersByTimeAsync(0);
      });
      // The stale rejection reconciled exactly once.
      expect(refreshUserMock).toHaveBeenCalledTimes(1);

      // The refresh failed transiently: the identity is cleared.
      act(() => {
        authMock.user = null;
      });
      rerender();
      expect(result.current.reconciling).toBe(true);

      // The recovery loop keeps asking /me on a cadence…
      await act(async () => {
        await rs.advanceTimersByTimeAsync(RECONCILE_RETRY_INTERVAL_MS);
      });
      expect(refreshUserMock).toHaveBeenCalledTimes(2);
      await act(async () => {
        await rs.advanceTimersByTimeAsync(RECONCILE_RETRY_INTERVAL_MS);
      });
      expect(refreshUserMock).toHaveBeenCalledTimes(3);

      // …until a complete identity returns; then the loop stops.
      act(() => {
        authMock.user = { id: "user-a", session_generation: 1756800000 };
      });
      rerender();
      const callsAfterRecovery = refreshUserMock.mock.calls.length;
      await act(async () => {
        await rs.advanceTimersByTimeAsync(RECONCILE_RETRY_INTERVAL_MS * 3);
      });
      expect(refreshUserMock.mock.calls.length).toBe(callsAfterRecovery);
    } finally {
      rs.useRealTimers();
    }
  });

  it("reconciles instead of rendering when the fence rejects the stale identity", async () => {
    // The race the backend fence closes: this tab still believes user-a,
    // the session cookie belongs to user-b, and the remount-fired list
    // request carries user-a's declaration. The fence answers 409 — no
    // wrong-account data may cross the boundary — and the only correct
    // client response is to reconcile the auth state, never to render.
    authMock.user = { id: "user-a", session_generation: 1756700000 };
    fetchMock.mockResolvedValue(staleIdentityResponse());
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => usePats(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.error).toBeInstanceOf(StaleSessionIdentityError);
    });
    expect(result.current.pats).toEqual([]);
    expect(
      queryClient.getQueryData(patQueryKey(identity("user-a", 1756700000))),
    ).toBeUndefined();
    await waitFor(() => {
      expect(refreshUserMock).toHaveBeenCalledTimes(1);
    });
  });
});
