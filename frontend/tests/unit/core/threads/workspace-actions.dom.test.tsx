import { afterEach, expect, it, rs } from "@rstest/core";
import { useQueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { useArchiveThread } from "@/core/threads/archive";
import {
  useBranchThread,
  useDeleteThread,
  useInfiniteThreads,
  useMoveThreadToProject,
  usePinThread,
  useRenameThread,
  useRunDetail,
  useThreads,
} from "@/core/threads/hooks";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace",
}));
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const user = {
  id: "alice",
  email: "alice@example.test",
  system_role: "user" as const,
  needs_setup: false,
};
type Row = {
  thread_id: string;
  values: { title: string };
  metadata: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
};
function fixture() {
  const seen: { path: string; method: string; workspace: string | null }[] = [];
  const data = new Map<string, Map<string, Row>>();
  for (const workspace of [P, T])
    data.set(
      workspace,
      new Map(
        ["parent", "sidecar"].map((id) => [
          id,
          {
            thread_id: id,
            values: { title: `${workspace}:${id}` },
            metadata:
              id === "sidecar"
                ? { deerflow_sidecar: true, parent_thread_id: "parent" }
                : {},
            status: "idle",
            created_at: "2026-10-14T00:00:00Z",
            updated_at: "2026-10-14T00:00:00Z",
          },
        ]),
      ),
    );
  let holdLookup = false;
  let release: (() => void) | undefined;
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        window.location.href,
      ).pathname;
      const workspace = new Headers(init?.headers).get("X-Deerflow-Workspace");
      const method = init?.method ?? "GET";
      seen.push({ path, method, workspace });
      if (path === "/api/workspaces")
        return Response.json(
          [P, T].map((id) => ({
            id,
            name: id === P ? "Personal" : "Team",
            kind: id === P ? "personal" : "team",
            status: "active",
            personal_user_id: id === P ? "alice" : null,
            role: "owner",
            membership_version: 1,
            policy_version: 1,
          })),
        );
      if (path === "/api/workspaces/current")
        return Response.json({
          actor_user_id: "alice",
          workspace_id: workspace,
          membership_version: 1,
          policy_version: 1,
        });
      const rows = data.get(workspace ?? P)!;
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as {
              metadata?: Record<string, unknown>;
              values?: { title: string };
              archived?: boolean;
              project_id?: string | null;
              offset?: number;
              limit?: number;
            })
          : {};
      if (path.endsWith("/threads/search")) {
        const values = [...rows.values()]
          .filter((row) =>
            body.metadata?.deerflow_sidecar === true
              ? row.metadata.deerflow_sidecar === true &&
                row.metadata.parent_thread_id === "parent"
              : row.metadata.deerflow_sidecar !== true &&
                (body.archived === undefined ||
                  (row.metadata.deerflow_archived === true) === body.archived),
          )
          .slice(body.offset ?? 0, (body.offset ?? 0) + (body.limit ?? 50));
        const response = Response.json(values);
        if (holdLookup && body.metadata?.deerflow_sidecar === true)
          response.json = () =>
            new Promise((resolve) => {
              release = () => resolve(values);
            });
        return response;
      }
      if (path.endsWith("/runs/run-1"))
        return Response.json({
          run_id: "run-1",
          thread_id: "parent",
          status: "success",
          metadata: { workspace },
        });
      if (path.endsWith("/parent/branches"))
        return Response.json({
          thread_id: `branch-${workspace}`,
          parent_thread_id: "parent",
          parent_checkpoint_id: "checkpoint",
          branched_from_message_id: "message",
          workspace_clone_mode: "copy",
        });
      if (path.endsWith("/parent/move")) {
        rows.get("parent")!.metadata.deerflow_project_id = body.project_id;
        return Response.json(rows.get("parent"));
      }
      if (path.endsWith("/parent/state")) {
        rows.get("parent")!.values = body.values!;
        return Response.json({ checkpoint_id: "checkpoint" });
      }
      const id = path.split("/").at(-1)!;
      if (method === "PATCH") {
        Object.assign(rows.get(id)!.metadata, body.metadata);
        return Response.json(rows.get(id));
      }
      if (method === "DELETE")
        return rows.delete(id)
          ? new Response(null, { status: 204 })
          : Response.json({ detail: "Not found" }, { status: 404 });
      throw new Error(`Unexpected thread action request ${method} ${path}`);
    },
  );
  return {
    seen,
    data,
    holdLookup: () => {
      holdLookup = true;
    },
    getRelease: () => release,
  };
}
function mount(
  callbacks: { onSuccess?: () => void; onError?: () => void } = {},
) {
  let control: WorkspaceContextValue | null = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  const view = renderHook(
    () => ({
      queryClient: useQueryClient(),
      list: useThreads(),
      infinite: useInfiniteThreads(),
      archived: useInfiniteThreads({ archived: true }),
      run: useRunDetail("parent", "run-1"),
      archive: useArchiveThread(callbacks),
      branch: useBranchThread(),
      pin: usePinThread(),
      move: useMoveThreadToProject({ onError: callbacks.onError }),
      rename: useRenameThread(),
      remove: useDeleteThread(),
    }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <StrictMode>
          <AuthProvider initialUser={user}>
            <QueryClientProvider>
              <WorkspaceProvider enabled>
                <Controls />
                <WorkspaceReadyBoundary>{children}</WorkspaceReadyBoundary>
              </WorkspaceProvider>
            </QueryClientProvider>
          </AuthProvider>
        </StrictMode>
      ),
    },
  );
  return {
    view,
    select: async () => {
      await act(async () => {
        expect(await control!.select(T)).toBe(true);
      });
    },
  };
}
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
});

it("keeps real sidebar search and thread actions in each confirmed space, with one canonical delete per thread", async () => {
  const server = fixture();
  const { view, select } = mount();
  for (const workspace of [P, T]) {
    if (workspace === T) await select();
    await waitFor(() =>
      expect(view.result.current.list.data?.[0]?.values.title).toBe(
        `${workspace}:parent`,
      ),
    );
    await waitFor(() =>
      expect(
        view.result.current.infinite.data?.pages[0]?.[0]?.values.title,
      ).toBe(`${workspace}:parent`),
    );
    await waitFor(() =>
      expect(view.result.current.run.data?.metadata).toEqual({ workspace }),
    );
    await act(async () => {
      await view.result.current.rename.mutateAsync({
        threadId: "parent",
        title: `renamed-${workspace}`,
      });
    });
    await waitFor(() =>
      expect(view.result.current.list.data?.[0]?.values.title).toBe(
        `renamed-${workspace}`,
      ),
    );
    await act(async () => {
      await view.result.current.pin.mutateAsync({
        threadId: "parent",
        pinned: true,
      });
    });
    await act(async () => {
      await view.result.current.archive.mutateAsync({
        threadId: "parent",
        archived: true,
      });
    });
    await waitFor(() =>
      expect(
        view.result.current.archived.data?.pages[0]?.[0]?.metadata
          ?.deerflow_archived,
      ).toBe(true),
    );
    await act(async () => {
      await view.result.current.archive.mutateAsync({
        threadId: "parent",
        archived: false,
      });
    });
    await act(async () => {
      await view.result.current.move.mutateAsync({
        threadId: "parent",
        projectId: `project-${workspace}`,
      });
    });
    await act(async () => {
      expect(
        (
          await view.result.current.branch.mutateAsync({
            threadId: "parent",
            messageId: "message",
          })
        ).thread_id,
      ).toBe(`branch-${workspace}`);
    });
    const onDeleted = rs.fn();
    await act(async () => {
      expect(
        await view.result.current.remove.mutateAsync({
          threadId: "parent",
          onDeleted,
        }),
      ).toEqual(["sidecar"]);
    });
    expect(onDeleted).toHaveBeenCalledTimes(1);
    expect(server.data.get(workspace)?.size).toBe(0);
    const deletes = server.seen.filter(
      (row) => row.method === "DELETE" && row.workspace === workspace,
    );
    expect(deletes.map((row) => row.path)).toEqual([
      "/api/threads/sidecar",
      "/api/threads/parent",
    ]);
  }
  expect(
    server.seen
      .filter((row) => row.path.includes("/threads/"))
      .every((row) => row.workspace === P || row.workspace === T),
  ).toBe(true);
});

it("abandons a delayed sidecar lookup on selection without deleting or firing the old completion", async () => {
  const server = fixture();
  const { view, select } = mount();
  await waitFor(() => expect(view.result.current.list.isSuccess).toBe(true));
  server.holdLookup();
  const onDeleted = rs.fn();
  const warning = rs.spyOn(console, "warn");
  let pending!: Promise<unknown>;
  act(() => {
    pending = view.result.current.remove
      .mutateAsync({ threadId: "parent", onDeleted })
      .catch((error: unknown) => error);
  });
  await waitFor(() => expect(server.getRelease()).toBeDefined());
  await select();
  await act(async () => {
    server.getRelease()!();
  });
  expect(await pending).toMatchObject({ name: "AbortError" });
  expect(server.seen.some((row) => row.method === "DELETE")).toBe(false);
  expect(onDeleted).not.toHaveBeenCalled();
  expect(warning).not.toHaveBeenCalled();
  expect(server.data.get(P)?.size).toBe(2);
  await waitFor(() =>
    expect(view.result.current.list.data?.[0]?.values.title).toBe(
      `${T}:parent`,
    ),
  );
});

it("fences archive publication across its real async cache cancellation and refuses retained mutation callbacks", async () => {
  const server = fixture();
  const onSuccess = rs.fn();
  const onError = rs.fn();
  const { view, select } = mount({ onSuccess, onError });
  await waitFor(() => expect(view.result.current.list.isSuccess).toBe(true));
  const old = view.result.current;
  const originalCancel = old.queryClient.cancelQueries.bind(old.queryClient);
  let release!: () => void;
  let entered = false;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  rs.spyOn(old.queryClient, "cancelQueries").mockImplementationOnce(
    async (filters, options) => {
      entered = true;
      await gate;
      return originalCancel(filters, options);
    },
  );
  let pending!: Promise<unknown>;
  act(() => {
    pending = old.archive
      .mutateAsync({ threadId: "parent", archived: true })
      .catch((error: unknown) => error);
  });
  await waitFor(() => expect(entered).toBe(true));
  await select();
  await act(async () => {
    release();
  });
  expect(await pending).toMatchObject({ name: "AbortError" });
  expect(onSuccess).not.toHaveBeenCalled();
  expect(onError).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(view.result.current.list.data?.[0]?.values.title).toBe(
      `${T}:parent`,
    ),
  );
  const count = server.seen.length;
  for (const mutate of [
    () => old.archive.mutateAsync({ threadId: "parent", archived: false }),
    () => old.branch.mutateAsync({ threadId: "parent", messageId: "message" }),
    () => old.pin.mutateAsync({ threadId: "parent", pinned: true }),
    () => old.move.mutateAsync({ threadId: "parent", projectId: null }),
    () => old.rename.mutateAsync({ threadId: "parent", title: "stale" }),
    () => old.remove.mutateAsync({ threadId: "parent" }),
  ])
    await expect(mutate()).rejects.toMatchObject({ name: "AbortError" });
  expect(server.seen).toHaveLength(count);
  expect(server.data.get(T)?.get("parent")?.metadata).toEqual({});
});
