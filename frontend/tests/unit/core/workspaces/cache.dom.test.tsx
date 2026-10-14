import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace",
}));

const alice: User = {
  id: "alice",
  email: "alice@example.test",
  system_role: "user",
  needs_setup: false,
};
const bob: User = { ...alice, id: "bob", email: "bob@example.test" };

afterEach(() => {
  cleanup();
});

describe("workspace query cache ownership", () => {
  it("gives independent mounted page trees their own cache without auth context", () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider>{children}</QueryClientProvider>
    );
    const first = renderHook(useQueryClient, { wrapper });
    const second = renderHook(useQueryClient, { wrapper });
    expect(first.result.current).not.toBe(second.result.current);
    first.result.current.setQueryData(["threads"], "private first page");
    expect(second.result.current.getQueryData(["threads"])).toBeUndefined();
  });

  it("replaces cache on workspace and authenticated actor change, cancelling old queries", async () => {
    let cacheKey = "workspace-a:lifetime-1";
    const wrapper = ({ children }: { children: ReactNode }) => (
      <AuthProvider initialUser={alice}>
        <QueryClientProvider cacheKey={cacheKey}>
          {children}
        </QueryClientProvider>
      </AuthProvider>
    );
    const view = renderHook(
      () => ({
        client: useQueryClient(),
        auth: useAuth(),
        query: useQuery({
          queryKey: ["threads"],
          queryFn: async () => "fresh",
          enabled: false,
        }),
      }),
      { wrapper },
    );
    const oldClient = view.result.current.client;
    act(() => {
      oldClient.setQueryData(["threads"], "Alice workspace A");
    });
    await waitFor(() =>
      expect(view.result.current.query.data).toBe("Alice workspace A"),
    );
    let oldSignal: AbortSignal | undefined;
    let finish!: (value: string) => void;
    const pending = oldClient
      .fetchQuery({
        queryKey: ["pending"],
        queryFn: ({ signal }) => {
          oldSignal = signal;
          return new Promise<string>((resolve) => {
            finish = resolve;
          });
        },
      })
      .catch(() => undefined);
    await waitFor(() => expect(oldSignal).toBeDefined());

    cacheKey = "workspace-b:lifetime-2";
    view.rerender();
    expect(view.result.current.client).not.toBe(oldClient);
    expect(view.result.current.query.data).toBeUndefined();
    await waitFor(() => expect(oldSignal?.aborted).toBe(true));
    expect(oldClient.getQueryCache().getAll()).toHaveLength(0);
    finish("late workspace A reply");
    await pending;
    expect(
      view.result.current.client.getQueryData(["pending"]),
    ).toBeUndefined();

    const teamClient = view.result.current.client;
    act(() => {
      teamClient.setQueryData(["threads"], "Alice workspace B");
    });
    await waitFor(() =>
      expect(view.result.current.query.data).toBe("Alice workspace B"),
    );
    act(() => {
      view.result.current.auth.applyUser(bob);
    });
    expect(view.result.current.client).not.toBe(teamClient);
    expect(view.result.current.query.data).toBeUndefined();
    await waitFor(() =>
      expect(teamClient.getQueryCache().getAll()).toHaveLength(0),
    );
    const bobClient = view.result.current.client;
    act(() => {
      bobClient.setQueryData(["threads"], "Bob private data");
    });
    act(() => {
      view.result.current.auth.applyUser(null);
    });
    expect(view.result.current.client).not.toBe(bobClient);
    expect(view.result.current.query.data).toBeUndefined();
    await waitFor(() =>
      expect(bobClient.getQueryCache().getAll()).toHaveLength(0),
    );
  });

  it("keeps live StrictMode queries connected and clears a truly unmounted page", async () => {
    const view = renderHook(
      () => ({
        client: useQueryClient(),
        query: useQuery({
          queryKey: ["report"],
          queryFn: async () => "ready",
          retry: false,
        }),
      }),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <StrictMode>
            <QueryClientProvider>{children}</QueryClientProvider>
          </StrictMode>
        ),
      },
    );
    await waitFor(() => expect(view.result.current.query.data).toBe("ready"));
    const client = view.result.current.client;
    expect(client.getQueryData(["report"])).toBe("ready");
    act(() => {
      client.setQueryData(["report"], "updated report");
    });
    await waitFor(() =>
      expect(view.result.current.query.data).toBe("updated report"),
    );
    view.unmount();
    await waitFor(() =>
      expect(client.getQueryCache().getAll()).toHaveLength(0),
    );
  });
});
