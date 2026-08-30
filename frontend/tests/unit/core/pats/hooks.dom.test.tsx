import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { type PropsWithChildren } from "react";

const fetchMock = rs.hoisted(() => rs.fn());

rs.mock("@/core/api/fetcher", () => ({
  fetch: fetchMock,
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "test-user" } }),
}));

import { patQueryKey, useRevokePat } from "@/core/pats/hooks";

function createWrapper(queryClient: QueryClient) {
  return function QueryWrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("useRevokePat", () => {
  beforeEach(() => {
    fetchMock.mockReset();
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
