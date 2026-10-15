import { afterEach, expect, it, rs } from "@rstest/core";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  waitFor,
  within,
} from "@testing-library/react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarProvider } from "@/components/ui/sidebar";
import { ArtifactFileDetail } from "@/components/workspace/artifacts/artifact-file-detail";
import { ArtifactFileList } from "@/components/workspace/artifacts/artifact-file-list";
import {
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts/context";
import { ThreadContext } from "@/components/workspace/messages/context";
import {
  downloadArtifactArchive,
  updateArtifactContent,
} from "@/core/artifacts/api";
import { loadArtifactContent } from "@/core/artifacts/loader";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

const mocks = rs.hoisted(() => ({
  path: "/workspace/chats/thread-1",
  error: rs.fn(),
  success: rs.fn(),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  usePathname: () => mocks.path,
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("sonner", () => ({
  toast: Object.assign(rs.fn(), {
    error: mocks.error,
    success: mocks.success,
    warning: rs.fn(),
    info: rs.fn(),
  }),
}));
rs.mock("@/components/workspace/code-editor", () => ({
  CodeEditor: ({
    value,
    readonly,
    disabled,
    onChange,
  }: {
    value: string;
    readonly?: boolean;
    disabled?: boolean;
    onChange?: (value: string) => void;
  }) => (
    <textarea
      aria-label="Artifact source"
      value={value}
      readOnly={readonly}
      disabled={disabled}
      onChange={(event) => onChange?.(event.target.value)}
    />
  ),
}));
rs.mock("@/components/workspace/artifacts/artifact-file-preview", () => ({
  ArtifactFilePreview: () => null,
  formatArtifactBytes: (bytes: number) => `${bytes} B`,
}));
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const FILE = "/mnt/user-data/outputs/report.txt";
function fixture(
  intercept?: (
    path: string,
    method: string,
    workspace: string | null,
    response: Response,
  ) => Response,
) {
  const reply = (
    path: string,
    method: string,
    workspace: string | null,
    response: Response,
  ) => intercept?.(path, method, workspace, response) ?? response;
  const rows = new Map<string, { content: string; sha: string }>();
  const seen: {
    path: string;
    method: string;
    workspace: string | null;
    body: unknown;
    range: string | null;
  }[] = [];
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        location.href,
      ).pathname;
      const headers = new Headers(init?.headers);
      const workspace = headers.get("X-Deerflow-Workspace");
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : {};
      seen.push({ path, method, workspace, body, range: headers.get("Range") });
      if (path === "/api/workspaces")
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
      if (path === "/api/workspaces/current")
        return Response.json({
          actor_user_id: "alice",
          workspace_id: workspace,
          membership_version: 1,
          policy_version: 1,
        });
      const threadId = path.split("/")[3] ?? "thread-1";
      const key = `${workspace}:${threadId}`;
      let row = rows.get(key);
      if (!row) {
        row = {
          content: `Report-${workspace}-${threadId}`,
          sha: (workspace === P ? "a" : "b").repeat(64),
        };
        rows.set(key, row);
      }
      if (path.endsWith("/artifacts/archive"))
        return reply(
          path,
          method,
          workspace,
          method === "GET"
            ? Response.json({ file_count: 2 })
            : new Response(`ZIP-${workspace}`, {
                headers: {
                  "Content-Disposition": `attachment; filename="report-${workspace}.zip"`,
                },
              }),
        );
      if (path.includes("/artifacts/")) {
        if (method === "PUT") {
          if (body.expected_sha256 !== row.sha)
            return Response.json({ detail: "stale revision" }, { status: 412 });
          if (typeof body.content !== "string")
            throw new Error("Invalid artifact request content");
          row.content = body.content;
          row.sha = (workspace === P ? "c" : "d").repeat(64);
          return reply(
            path,
            method,
            workspace,
            Response.json({
              path: FILE,
              sha256: row.sha,
              size: row.content.length,
            }),
          );
        }
        return reply(
          path,
          method,
          workspace,
          new Response(row.content, {
            headers: { ETag: `"${row.sha}"`, "Content-Type": "text/plain" },
          }),
        );
      }
      throw new Error(`Unexpected artifact request ${method} ${path}`);
    },
  );
  const create = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:artifact-test");
  const revoke = rs
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => undefined);
  const downloads: string[] = [];
  rs.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download);
  });
  return { seen, create, revoke, downloads };
}
function mount() {
  let control: WorkspaceContextValue | null = null;
  let cache: QueryClient | null = null;
  let state: ReturnType<typeof useArtifacts> | null = null;
  let life: ReturnType<typeof useWorkspaceLifetime> = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  function Content() {
    cache = useQueryClient();
    state = useArtifacts();
    life = useWorkspaceLifetime();
    const threadId = mocks.path.split("/").at(-1)!;
    return (
      <>
        <output data-testid="artifact-state">
          {JSON.stringify({
            artifacts: state.artifacts,
            selected: state.selectedArtifact,
            open: state.open,
          })}
        </output>
        <ThreadContext.Provider
          value={{
            thread: { messages: [], isLoading: false } as never,
            isMock: false,
          }}
        >
          <ArtifactFileDetail filepath={FILE} threadId={threadId} />
          <div data-testid="file-list">
            <ArtifactFileList
              files={[FILE]}
              threadId={threadId}
              runId="run-1"
            />
          </div>
        </ThreadContext.Provider>
      </>
    );
  }
  const tree = () => (
    <AuthProvider
      initialUser={{
        id: "alice",
        email: "alice@example.test",
        system_role: "user",
        needs_setup: false,
      }}
    >
      <QueryClientProvider>
        <I18nContext.Provider
          value={{ locale: "en-US", t: enUS, setLocale: () => undefined }}
        >
          <WorkspaceProvider enabled>
            <Controls />
            <WorkspaceReadyBoundary>
              <SidebarProvider>
                <ArtifactsProvider>
                  <Content />
                </ArtifactsProvider>
              </SidebarProvider>
            </WorkspaceReadyBoundary>
          </WorkspaceProvider>
        </I18nContext.Provider>
      </QueryClientProvider>
    </AuthProvider>
  );
  const view = render(tree());
  return {
    view,
    cache: () => cache!,
    state: () => state!,
    lifetime: () => life!,
    route: (path: string) => {
      mocks.path = path;
      view.rerender(tree());
    },
    select: async (id: string) => {
      await act(async () => {
        expect(await control!.select(id)).toBe(true);
      });
    },
  };
}
afterEach(() => {
  cleanup();
  sessionStorage.clear();
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
  rs.clearAllMocks();
  mocks.path = "/workspace/chats/thread-1";
});
function source(app: ReturnType<typeof mount>) {
  const editor = app.view.getByRole("textbox", { name: "Artifact source" });
  if (!(editor instanceof HTMLTextAreaElement))
    throw new Error("Artifact editor missing");
  return editor;
}
it("uses each workspace for the real artifact preview, revision save, panel state and ZIP download", async () => {
  const net = fixture();
  const legacyKey = `deerflow:artifacts:v1:${encodeURIComponent(mocks.path)}`;
  sessionStorage.setItem(
    legacyKey,
    JSON.stringify({
      artifacts: ["/legacy.txt"],
      selectedArtifact: "/legacy.txt",
      open: true,
    }),
  );
  const app = mount();
  for (const space of [P, T]) {
    if (space === T) await app.select(T);
    await waitFor(() =>
      expect(source(app).value).toBe(`Report-${space}-thread-1`),
    );
    expect(
      JSON.parse(app.view.getByTestId("artifact-state").textContent),
    ).toEqual({ artifacts: [], selected: null, open: false });
    fireEvent.click(
      within(app.view.getByTestId("file-list")).getByText("report.txt"),
    );
    await waitFor(() => expect(app.state().selectedArtifact).toBe(FILE));
    fireEvent.click(app.view.getByRole("button", { name: "Edit" }));
    fireEvent.change(source(app), { target: { value: `Edited-${space}` } });
    const before = mocks.success.mock.calls.length;
    fireEvent.click(app.view.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mocks.success).toHaveBeenCalledTimes(before + 1),
    );
    expect(app.state().drafts[FILE]).toMatchObject({
      baselineContent: `Edited-${space}`,
      draftContent: `Edited-${space}`,
      conflict: false,
    });
    fireEvent.click(
      await app.view.findByRole("button", {
        name: /Download current versions/,
      }),
    );
    await waitFor(() =>
      expect(net.downloads).toHaveLength(space === P ? 1 : 2),
    );
  }
  expect(net.downloads).toEqual([`report-${P}.zip`, `report-${T}.zip`]);
  for (const [index, space] of [P, T].entries()) {
    const blob = net.create.mock.calls[index]![0];
    if (!(blob instanceof Blob)) throw new Error("ZIP Blob missing");
    expect(await blob.text()).toBe(`ZIP-${space}`);
  }
  expect(net.revoke).toHaveBeenCalledTimes(2);
  expect(mocks.error).not.toHaveBeenCalled();
  const writes = net.seen.filter((row) => row.method === "PUT");
  expect(writes.map((row) => [row.workspace, row.body])).toEqual([
    [P, { content: `Edited-${P}`, expected_sha256: "a".repeat(64) }],
    [T, { content: `Edited-${T}`, expected_sha256: "b".repeat(64) }],
  ]);
  expect(
    net.seen
      .filter((row) => row.path.includes("/artifacts/"))
      .every((row) => row.workspace === P || row.workspace === T),
  ).toBe(true);
  expect(sessionStorage.getItem(legacyKey)).toContain("legacy.txt");
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
it("ignores old save, download and panel callbacks after same-space navigation without remounting the chat", async () => {
  const save = deferred<void>();
  const zip = deferred<void>();
  const saveEntered = deferred<void>();
  const zipEntered = deferred<void>();
  const saveDecoded = deferred<void>();
  const zipDecoded = deferred<void>();
  const net = fixture((path, method, _workspace, response) => {
    if (path.includes("/thread-1/") && method === "PUT") {
      const decode = response.json.bind(response);
      rs.spyOn(response, "json").mockImplementation(async () => {
        saveEntered.resolve();
        await save.promise;
        const result: unknown = await decode();
        saveDecoded.resolve();
        return result;
      });
    }
    if (
      path.includes("/thread-1/") &&
      path.endsWith("/archive") &&
      method === "POST"
    ) {
      const decode = response.blob.bind(response);
      rs.spyOn(response, "blob").mockImplementation(async () => {
        zipEntered.resolve();
        await zip.promise;
        const result = await decode();
        zipDecoded.resolve();
        return result;
      });
    }
    return response;
  });
  const app = mount();
  await waitFor(() => expect(source(app).value).toBe(`Report-${P}-thread-1`));
  const old = app.state();
  const cache = app.cache();
  const life = app.lifetime();
  fireEvent.click(app.view.getByRole("button", { name: "Edit" }));
  fireEvent.change(source(app), { target: { value: "old unsaved" } });
  fireEvent.click(app.view.getByRole("button", { name: "Save" }));
  await saveEntered.promise;
  fireEvent.click(
    await app.view.findByRole("button", { name: /Download current versions/ }),
  );
  await zipEntered.promise;
  app.route("/workspace/chats/thread-2");
  await waitFor(() => expect(source(app).value).toBe(`Report-${P}-thread-2`));
  expect(app.cache()).toBe(cache);
  expect(app.lifetime()).toBe(life);
  fireEvent.click(app.view.getByRole("button", { name: "Edit" }));
  fireEvent.change(source(app), { target: { value: "new unsaved" } });
  act(() => {
    old.select("/expired.txt");
    old.setOpen(true);
    old.setArtifacts(["/expired.txt"]);
    old.setDrafts({});
    old.setEditingPath(null);
  });
  await act(async () => {
    save.resolve();
    zip.resolve();
    await Promise.all([saveDecoded.promise, zipDecoded.promise]);
  });
  expect(source(app).value).toBe("new unsaved");
  expect(app.state().editingPath).toBe(FILE);
  expect(app.state().selectedArtifact).toBeNull();
  expect(app.state().artifacts).toEqual([]);
  expect(net.create).not.toHaveBeenCalled();
  expect(mocks.success).not.toHaveBeenCalled();
  expect(mocks.error).not.toHaveBeenCalled();
  // New operations remain usable; an old finally must not disable this owner.
  fireEvent.click(app.view.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(mocks.success).toHaveBeenCalledTimes(1));
  expect(app.state().drafts[FILE]?.baselineContent).toBe("new unsaved");
  fireEvent.click(
    await app.view.findByRole("button", { name: /Download current versions/ }),
  );
  await waitFor(() => expect(net.downloads).toHaveLength(1));
  app.route("/workspace/chats/thread-1");
  await waitFor(() => expect(source(app).value).toBe("old unsaved"));
  act(() => {
    old.setDrafts({});
    old.select("/expired-again.txt");
    old.setOpen(true);
  });
  expect(app.state().selectedArtifact).toBeNull();
  expect(app.state().drafts[FILE]?.baselineContent).toBe("old unsaved");
});
it("rejects complete native byte, JSON and Blob decoders when their captured workspace expires", async () => {
  const gates = [deferred<void>(), deferred<void>(), deferred<void>()];
  const entered = [deferred<void>(), deferred<void>(), deferred<void>()];
  let armed = false;
  fixture((path, method, _workspace, response) => {
    if (!armed) return response;
    const index = method === "PUT" ? 1 : method === "POST" ? 2 : 0;
    if (!path.includes("/artifacts/")) return response;
    if (index === 0) {
      const decode = response.arrayBuffer.bind(response);
      rs.spyOn(response, "arrayBuffer").mockImplementation(async () => {
        entered[0]!.resolve();
        await gates[0]!.promise;
        return decode();
      });
    }
    if (index === 1) {
      const decode = response.json.bind(response);
      rs.spyOn(response, "json").mockImplementation(async () => {
        entered[1]!.resolve();
        await gates[1]!.promise;
        return decode() as Promise<unknown>;
      });
    }
    if (index === 2) {
      const decode = response.blob.bind(response);
      rs.spyOn(response, "blob").mockImplementation(async () => {
        entered[2]!.resolve();
        await gates[2]!.promise;
        return decode();
      });
    }
    return response;
  });
  const app = mount();
  await waitFor(() => expect(source(app).value).toBe(`Report-${P}-thread-1`));
  const old = app.lifetime();
  armed = true;
  const options = { rest: old.rest, signal: old.scope.signal };
  const results = Promise.allSettled([
    loadArtifactContent({ threadId: "thread-1", filepath: FILE }, options),
    updateArtifactContent(
      {
        threadId: "thread-1",
        filepath: FILE,
        content: "old save",
        expectedSha256: "a".repeat(64),
      },
      options,
    ),
    downloadArtifactArchive({ threadId: "thread-1", runId: "run-1" }, options),
  ]);
  await Promise.all(entered.map((item) => item.promise));
  armed = false;
  await app.select(T);
  await waitFor(() => expect(source(app).value).toBe(`Report-${T}-thread-1`));
  expect(old.scope.signal.aborted).toBe(true);
  await act(async () => {
    gates.forEach((item) => item.resolve());
    const settled = await results;
    for (const row of settled) {
      expect(row.status).toBe("rejected");
      if (row.status === "rejected")
        expect(row.reason).toMatchObject({ name: "AbortError" });
    }
  });
  expect(source(app).value).toBe(`Report-${T}-thread-1`);
  expect(mocks.error).not.toHaveBeenCalled();
  expect(mocks.success).not.toHaveBeenCalled();
});
