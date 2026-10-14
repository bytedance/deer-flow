import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { AuthProvider } from "@/core/auth/AuthProvider";
import {
  useDeleteUploadedFile,
  useUploadedFiles,
  useUploadFiles,
  useUploadLimits,
} from "@/core/uploads/hooks";
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
function fixture() {
  const seen: {
    path: string;
    method: string;
    workspace: string | null;
    body: BodyInit | null | undefined;
  }[] = [];
  let hold = false;
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
      seen.push({ path, workspace, method, body: init?.body });
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
      if (path.endsWith("/uploads/limits"))
        return Response.json({
          max_files: 5,
          max_file_size: 100,
          max_total_size: 500,
        });
      if (path.endsWith("/uploads/list"))
        return Response.json({
          files: [{ filename: workspace, size: 1 }],
          count: 1,
        });
      if (method === "DELETE")
        return Response.json({ success: true, message: "Deleted" });
      if (method === "POST" && path.endsWith("/uploads")) {
        const response = Response.json({
          success: true,
          files: [{ filename: workspace, size: 1 }],
          skipped_files: [],
          message: "Uploaded",
        });
        if (hold)
          response.json = () =>
            new Promise((resolve) => {
              release = () =>
                resolve({
                  success: true,
                  files: [{ filename: workspace }],
                  skipped_files: [],
                  message: "Uploaded",
                });
            });
        return response;
      }
      throw new Error(`Unexpected upload request ${path}`);
    },
  );
  return {
    seen,
    delayBody: () => {
      hold = true;
    },
    getRelease: () => release,
  };
}
function mount() {
  let control: WorkspaceContextValue | null = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  const view = renderHook(
    () => ({
      upload: useUploadFiles("thread-1"),
      list: useUploadedFiles("thread-1"),
      limits: useUploadLimits("thread-1"),
      remove: useDeleteUploadedFile("thread-1"),
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
});

it("uses the confirmed workspace in real upload/list/limits/delete hooks and starts a clean team cache", async () => {
  const server = fixture();
  const { view, select } = mount();
  await waitFor(() =>
    expect(view.result.current.list.data?.files[0]?.filename).toBe(P),
  );
  expect(view.result.current.limits.data?.max_files).toBe(5);
  await act(async () => {
    await view.result.current.upload.mutateAsync([
      new File(["report"], "report.txt"),
    ]);
  });
  await act(async () => {
    await view.result.current.remove.mutateAsync("report#1?.txt");
  });
  const upload = server.seen.find((row) => row.method === "POST");
  expect(upload?.workspace).toBe(P);
  expect((upload?.body as FormData).get("files")).toBeInstanceOf(File);
  expect(
    server.seen.some(
      (row) => row.path.endsWith("/report%231%3F.txt") && row.workspace === P,
    ),
  ).toBe(true);
  await select();
  await waitFor(() =>
    expect(view.result.current.list.data?.files[0]?.filename).toBe(T),
  );
  await act(async () => {
    expect(
      (await view.result.current.upload.mutateAsync([])).files[0]?.filename,
    ).toBe(T);
  });
  expect(
    server.seen
      .filter((row) => row.path.includes("/uploads"))
      .every((row) => row.workspace === P || row.workspace === T),
  ).toBe(true);
});

it("rejects a decoded late upload and a retained old submit callback after switching workspace", async () => {
  const server = fixture();
  const { view, select } = mount();
  await waitFor(() => expect(view.result.current.list.isSuccess).toBe(true));
  const retainedUpload = view.result.current.upload.mutateAsync;
  server.delayBody();
  let pending!: Promise<unknown>;
  act(() => {
    pending = retainedUpload([]).then(
      (value) => ({ value }),
      (error) => ({ error }),
    );
  });
  await waitFor(() => expect(server.getRelease()).toBeDefined());
  await select();
  await act(async () => {
    server.getRelease()!();
  });
  const outcome = (await pending) as { error?: Error; value?: unknown };
  expect(outcome.value).toBeUndefined();
  expect(outcome.error?.name).toBe("AbortError");
  const count = server.seen.length;
  await expect(retainedUpload([])).rejects.toMatchObject({
    name: "AbortError",
  });
  expect(server.seen).toHaveLength(count);
  expect(view.result.current.upload.data).toBeUndefined();
});
