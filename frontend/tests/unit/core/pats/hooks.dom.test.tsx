import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { type PropsWithChildren } from "react";

const fetchMock = rs.hoisted(() => rs.fn());
// Mutable on purpose: the identity-switch regression needs to change the
// authenticated user between renders, which the static useAuth mock can't.
const authMock = rs.hoisted(() => ({
  user: { id: "test-user" } as { id: string } | null,
}));

rs.mock("@/core/api/fetcher", () => ({
  fetch: fetchMock,
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: authMock.user }),
}));

import { patQueryKey, usePats, useRevokePat } from "@/core/pats/hooks";
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

describe("useRevokePat", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    authMock.user = { id: "test-user" };
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
        queryKey: patQueryKey("test-user"),
      });
    });
    expect(settled).toBe(false);

    await act(async () => {
      finishRefresh();
      await revokePromise;
    });
    expect(settled).toBe(true);
  });
});

describe("usePats", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    authMock.user = { id: "user-a" };
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
      authMock.user = { id: "user-b" };
    });
    rerender();

    await waitFor(() => {
      expect(result.current.pats.map((pat) => pat.id)).toEqual(["pat-b"]);
    });
    expect(queryClient.getQueryData(patQueryKey("user-a"))).toBeUndefined();
    expect(queryClient.getQueryData(patQueryKey("user-b"))).toEqual([
      summary("pat-b"),
    ]);
  });
});
