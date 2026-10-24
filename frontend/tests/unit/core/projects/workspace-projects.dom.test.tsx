import { afterEach, expect, it, rs } from "@rstest/core";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { fetchProjectDocumentPreview } from "@/core/projects/api";
import {
  useProjects,
  useProject,
  useProjectsConfig,
  useInfiniteProjectThreads,
  useInfiniteProjectDocuments,
  useInfiniteProjectThreadFiles,
  useCreateProject,
  usePatchProject,
  useArchiveProject,
  useRestoreProject,
  useDeleteProject,
  useUploadProjectDocument,
  usePromoteThreadFile,
  useAttachProjectDocument,
  useDeleteProjectDocument,
} from "@/core/projects/hooks";
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
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const pending = new Set<() => void>();
function fixture() {
  let hold = false;
  function delayBody(
    response: Response,
    method: "json" | "arrayBuffer",
    workspace: string | null,
  ) {
    if (!hold || workspace !== P) return response;
    const decode = response[method].bind(response);
    Object.defineProperty(response, method, {
      value: async () => {
        const value: unknown = await decode();
        return new Promise((resolve) => {
          const release = () => {
            pending.delete(release);
            resolve(value);
          };
          pending.add(release);
        });
      },
    });
    return response;
  }
  const seen: {
    path: string;
    method: string;
    workspace: string | null;
    body: unknown;
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
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as unknown)
          : init?.body;
      seen.push({ path: url.pathname, workspace, method, body });
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
      const project = {
        id: "project-1",
        name: `${workspace}-project`,
        instructions: "Research",
        presentation: {},
        status: url.pathname.endsWith("/archive") ? "archived" : "active",
        created_at: "2026-10-15T00:00:00Z",
        updated_at: "2026-10-15T00:00:00Z",
      };
      const document = {
        id: "doc-1",
        name: `report-${workspace}.md`,
        size_bytes: 12,
        sha256: "fixture",
        content_missing: false,
        source_thread_id: null,
        source_kind: null,
        source_name: null,
        created_at: project.created_at,
        updated_at: project.updated_at,
      };
      if (url.pathname === "/api/projects/config")
        return Response.json({
          instructions_max_bytes: 8192,
          trash_retention_days: 30,
        });
      if (url.pathname === "/api/projects")
        return Response.json(
          method === "GET" ? { projects: [project] } : project,
        );
      if (url.pathname === "/api/projects/project-1/threads")
        return Response.json([{ thread_id: `${workspace}-thread` }]);
      if (url.pathname === "/api/projects/project-1/thread-files")
        return Response.json({
          groups: [],
          next_offset: null,
          truncated: false,
        });
      if (url.pathname === "/api/projects/project-1/documents")
        return method === "GET"
          ? Response.json({
              documents: [document],
              total: 1,
              limit: 100,
              offset: 0,
            })
          : delayBody(
              Response.json({ document, deduplicated: false }),
              "json",
              workspace,
            );
      if (url.pathname.endsWith("/documents/from-thread"))
        return Response.json({ document, deduplicated: false });
      if (url.pathname.endsWith("/attach-to-thread/thread-1"))
        return Response.json({
          filename: document.name,
          size_bytes: 12,
          virtual_path: `/mnt/user-data/uploads/${document.name}`,
          artifact_url: `/api/threads/thread-1/artifacts/mnt/user-data/uploads/${document.name}`,
        });
      if (url.pathname.endsWith("/content"))
        return delayBody(
          new Response(`report-${workspace}`, {
            headers: { "Content-Type": "text/plain" },
          }),
          "arrayBuffer",
          workspace,
        );
      if (method === "DELETE") return new Response(null, { status: 204 });
      if (url.pathname.startsWith("/api/projects/project-1"))
        return Response.json(project);
      throw new Error(`Unexpected request: ${method} ${url}`);
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
function useProjectFlow() {
  return {
    projects: useProjects(),
    project: useProject("project-1"),
    config: useProjectsConfig(),
    threads: useInfiniteProjectThreads("project-1"),
    documents: useInfiniteProjectDocuments("project-1"),
    files: useInfiniteProjectThreadFiles("project-1"),
    create: useCreateProject(),
    patch: usePatchProject(),
    archive: useArchiveProject(),
    restore: useRestoreProject(),
    remove: useDeleteProject(),
    upload: useUploadProjectDocument("project-1"),
    promote: usePromoteThreadFile("project-1"),
    attach: useAttachProjectDocument("project-1"),
    trash: useDeleteProjectDocument("project-1"),
  };
}
function mount() {
  let control: WorkspaceContextValue | null = null;
  let flow: ReturnType<typeof useProjectFlow> | null = null;
  let cache: QueryClient | null = null;
  let lifetime: ReturnType<typeof useWorkspaceLifetime> = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  function Probe() {
    cache = useQueryClient();
    lifetime = useWorkspaceLifetime();
    flow = useProjectFlow();
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
    flow: () => flow!,
    cache: () => cache!,
    lifetime: () => lifetime!,
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
it("uses each space for native project, shelf and conversation file workflows", async () => {
  const { seen } = fixture();
  const app = mount();
  const run = async (space: string) => {
    await waitFor(() =>
      expect(app.flow().projects.data?.[0]?.name).toBe(`${space}-project`),
    );
    await waitFor(() =>
      expect(app.flow().documents.data?.pages[0]?.documents[0]?.name).toBe(
        `report-${space}.md`,
      ),
    );
    await waitFor(() =>
      expect(app.flow().threads.data?.pages[0]?.[0]?.thread_id).toBe(
        `${space}-thread`,
      ),
    );
    await waitFor(() => expect(app.flow().files.isSuccess).toBe(true));
    await act(async () => {
      expect(
        (await app.flow().create.mutateAsync({ name: "Research" })).id,
      ).toBe("project-1");
      await app.flow().patch.mutateAsync({
        projectId: "project-1",
        input: { instructions: "With sources" },
      });
      const uploaded = await app
        .flow()
        .upload.mutateAsync({ file: new File(["report"], "report.md") });
      expect(uploaded.document.name).toBe(`report-${space}.md`);
      const attached = await app
        .flow()
        .attach.mutateAsync({ documentId: "doc-1", threadId: "thread-1" });
      expect(attached.filename).toBe(`report-${space}.md`);
      await app.flow().promote.mutateAsync({
        thread_id: "thread-1",
        kind: "output",
        name: "report.md",
      });
      const life = app.lifetime();
      const preview = await fetchProjectDocumentPreview("project-1", "doc-1", {
        rest: life.rest,
        signal: life.scope.signal,
      });
      expect(preview).toMatchObject({
        kind: "text",
        content: `report-${space}`,
        truncated: false,
      });
      expect((await app.flow().archive.mutateAsync("project-1")).status).toBe(
        "archived",
      );
      await app.flow().restore.mutateAsync("project-1");
      await app.flow().trash.mutateAsync("doc-1");
      await app.flow().remove.mutateAsync("project-1");
    });
  };
  await run(P);
  const old = app.cache();
  await app.select();
  expect(app.cache()).not.toBe(old);
  await run(T);
  const projectRequests = seen.filter((row) =>
    row.path.startsWith("/api/projects"),
  );
  expect(
    projectRequests.every((row) => row.workspace === P || row.workspace === T),
  ).toBe(true);
  for (const space of [P, T]) {
    const rows = projectRequests.filter((row) => row.workspace === space);
    const upload = rows.find(
      (row) => row.path.endsWith("/documents") && row.method === "POST",
    );
    expect(upload?.body).toBeInstanceOf(FormData);
    expect((upload!.body as FormData).get("file")).toBeInstanceOf(File);
    expect(rows.find((row) => row.method === "PATCH")?.body).toEqual({
      instructions: "With sources",
    });
    expect(
      rows.filter((row) => row.method === "DELETE").map((row) => row.path),
    ).toEqual([
      "/api/projects/project-1/documents/doc-1",
      "/api/projects/project-1",
    ]);
  }
});

it("rejects late shelf upload/preview bodies and retained project mutations after a switch", async () => {
  const net = fixture();
  const app = mount();
  await waitFor(() => expect(app.flow().documents.isSuccess).toBe(true));
  const oldCache = app.cache();
  const oldRemove = app.flow().remove.mutateAsync;
  const life = app.lifetime();
  net.hold();
  const done = Promise.allSettled([
    app.flow().upload.mutateAsync({ file: new File(["late"], "late.md") }),
    fetchProjectDocumentPreview("project-1", "doc-1", {
      rest: life.rest,
      signal: life.scope.signal,
    }),
  ]);
  await waitFor(() => expect(pending.size).toBe(2));
  await app.select();
  const invalidate = rs.spyOn(oldCache, "invalidateQueries");
  let outcomes: PromiseSettledResult<unknown>[] = [];
  await act(async () => {
    net.resume();
    outcomes = await done;
  });
  expect(outcomes.map((result) => result.status)).toEqual([
    "rejected",
    "rejected",
  ]);
  for (const result of outcomes)
    if (result.status === "rejected")
      expect(result.reason).toMatchObject({ name: "AbortError" });
  const requestCount = net.seen.filter((row) => row.method === "DELETE").length;
  await act(async () => {
    await expect(oldRemove("project-1")).rejects.toMatchObject({
      name: "AbortError",
    });
  });
  expect(net.seen.filter((row) => row.method === "DELETE")).toHaveLength(
    requestCount,
  );
  expect(invalidate).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(app.flow().documents.data?.pages[0]?.documents[0]?.name).toBe(
      `report-${T}.md`,
    ),
  );
  await act(async () => {
    expect(
      (
        await app
          .flow()
          .upload.mutateAsync({ file: new File(["current"], "current.md") })
      ).document.name,
    ).toBe(`report-${T}.md`);
  });
});
