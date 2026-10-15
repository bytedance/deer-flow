import { afterEach, expect, it, rs } from "@rstest/core";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { AuthProvider } from "@/core/auth/AuthProvider";
import {
  markThreadRead,
  pollThreadActivity,
  threadActivityState,
  useMarkThreadRead,
  useThreadActivity,
} from "@/core/threads/activity";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace",
}));
rs.mock("@/core/features/hooks", () => ({
  useThreadActivityFeature: () => ({ available: true, isLoading: false }),
}));
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const pending = new Set<() => void>();
function fixture() {
  let hold = false;
  const reply = (body: unknown, workspace: string | null) => {
    const response = Response.json(body);
    if (hold && workspace === P)
      Object.defineProperty(response, "json", {
        value: () =>
          new Promise((resolve) => {
            const release = () => {
              pending.delete(release);
              resolve(body);
            };
            pending.add(release);
          }),
      });
    return response;
  };
  const seen: {
    path: string;
    workspace: string | null;
    cursor: string | null;
  }[] = [];
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        window.location.href,
      );
      const workspace = new Headers(init?.headers).get("X-Deerflow-Workspace");
      seen.push({
        path: url.pathname,
        workspace,
        cursor: url.searchParams.get("cursor"),
      });
      if (url.pathname === "/api/workspaces")
        return Response.json(
          [P, T].map((id) => ({
            id,
            name: id,
            kind: id === P ? "personal" : "team",
            personal_user_id: id === P ? "alice" : null,
            status: "active",
            role: "owner",
            membership_version: 1,
            policy_version: 1,
          })),
        );
      if (url.pathname === "/api/workspaces/current")
        return Response.json({
          actor_user_id: "alice",
          workspace_id: workspace,
          membership_version: 1,
          policy_version: 1,
        });
      if (url.pathname === "/api/thread-activity")
        return reply(
          {
            cursor: `${workspace}:cursor`,
            threads: [],
            truncated: false,
            read_version: workspace === P ? 4 : 10,
          },
          workspace,
        );
      if (url.pathname.endsWith("/read"))
        return reply(
          { unread: false, read_version: workspace === P ? 5 : 11 },
          workspace,
        );
      throw new Error(`Unexpected request: ${url}`);
    },
  );
  return {
    seen,
    hold: () => {
      hold = true;
    },
    resume: () => {
      hold = false;
      for (const release of [...pending]) release();
    },
  };
}
function mount() {
  let control: WorkspaceContextValue | null = null;
  let cache: QueryClient | null = null;
  let read: (() => void) | null = null;
  let lifetime: ReturnType<typeof useWorkspaceLifetime> = null;
  let refresh: (() => Promise<unknown>) | null = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  function Probe() {
    cache = useQueryClient();
    lifetime = useWorkspaceLifetime();
    read = useMarkThreadRead("thread-1");
    const activity = useThreadActivity();
    refresh = activity.refetch;
    return null;
  }
  render(
    <AuthProvider
      initialUser={{
        id: "alice",
        email: "alice@example.test",
        system_role: "user",
        needs_setup: false,
      }}
    >
      <QueryClientProvider>
        <WorkspaceProvider enabled>
          <Controls />
          <WorkspaceReadyBoundary>
            <Probe />
          </WorkspaceReadyBoundary>
        </WorkspaceProvider>
      </QueryClientProvider>
    </AuthProvider>,
  );
  return {
    lifetime: () => lifetime!,
    cache: () => cache!,
    read: () => read!,
    refresh: () => refresh!(),
    select: async () => {
      await act(async () => {
        expect(await control!.select(T)).toBe(true);
      });
    },
  };
}
afterEach(() => {
  for (const release of [...pending]) release();
  cleanup();
  rs.unstubAllGlobals();
  sessionStorage.clear();
});
it("polls and marks reads with independent workspace cursors and clocks", async () => {
  const { seen } = fixture();
  const app = mount();
  await waitFor(() =>
    expect(threadActivityState(app.cache()).cursor).toBe(`${P}:cursor`),
  );
  const personal = app.cache();
  act(() => app.read()());
  await waitFor(
    () => expect(threadActivityState(personal).readVersion).toBe(5),
    { timeout: 3000 },
  );
  await app.select();
  await waitFor(() =>
    expect(threadActivityState(app.cache()).cursor).toBe(`${T}:cursor`),
  );
  expect(app.cache()).not.toBe(personal);
  act(() => app.read()());
  await waitFor(
    () => expect(threadActivityState(app.cache()).readVersion).toBe(11),
    { timeout: 3000 },
  );
  await act(async () => {
    await app.refresh();
  });
  expect(
    seen
      .filter((row) => row.path.endsWith("/read"))
      .map((row) => row.workspace),
  ).toEqual([P, T]);
  expect(
    seen
      .filter((row) => row.path === "/api/thread-activity")
      .map((row) => [row.workspace, row.cursor]),
  ).toEqual([
    [P, null],
    [T, null],
    [T, `${T}:cursor`],
  ]);
});

it("ignores old activity/read bodies and retained callbacks after switching spaces", async () => {
  const net = fixture();
  const app = mount();
  await waitFor(() =>
    expect(threadActivityState(app.cache()).cursor).toBe(`${P}:cursor`),
  );
  const oldCache = app.cache();
  const oldRead = app.read();
  const lifetime = app.lifetime();
  const request = { rest: lifetime.rest, signal: lifetime.scope.signal };
  net.hold();
  const done = Promise.allSettled([
    pollThreadActivity(oldCache, request),
    markThreadRead(oldCache, "thread-1", request),
  ]);
  await waitFor(() => expect(pending.size).toBe(2));
  // New requests answer normally; the two old response bodies remain held.
  await app.select();
  const invalidate = rs.spyOn(oldCache, "invalidateQueries");
  net.resume();
  await act(async () => {
    await done;
  });
  await waitFor(() =>
    expect(threadActivityState(app.cache()).cursor).toBe(`${T}:cursor`),
  );
  expect(threadActivityState(oldCache)).toEqual({
    cursor: null,
    readVersion: null,
  });
  act(() => oldRead());
  act(() => app.read()());
  await waitFor(
    () => expect(threadActivityState(app.cache()).readVersion).toBe(11),
    { timeout: 3000 },
  );
  expect(invalidate).not.toHaveBeenCalled();
  expect(
    net.seen
      .filter((row) => row.path.endsWith("/read"))
      .map((row) => row.workspace),
  ).toEqual([P, T]);
});
