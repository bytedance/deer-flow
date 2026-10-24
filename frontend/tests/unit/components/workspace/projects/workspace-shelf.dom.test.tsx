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
import { useEffect, useState } from "react";

import {
  PromptInputProvider,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { QueryClientProvider } from "@/components/query-client-provider";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { ProjectDocumentsSection } from "@/components/workspace/projects/project-documents-section";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  readProjectAttachments,
  stageProjectAttachment,
} from "@/core/projects/composer-attach";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

const mocks = rs.hoisted(() => ({
  push: rs.fn(),
  error: rs.fn(),
  success: rs.fn(),
  submit:
    rs.fn<
      (message: PromptInputMessage, options?: InputBoxSubmitOptions) => void
    >(),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: rs.fn() }),
  usePathname: () => "/workspace",
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
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [],
    tokenUsageEnabled: false,
    isLoading: false,
    isFetching: false,
  }),
}));
rs.mock("@/components/workspace/artifacts/artifact-file-preview", () => ({
  ArtifactFilePreview: () => null,
  formatArtifactBytes: (bytes: number) => `${bytes} B`,
}));
rs.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const pending = new Set<() => void>();
function fixture() {
  let hold: "attach" | "upload" | null = null;
  const delayed = (
    response: Response,
    kind: "attach" | "upload",
    workspace: string | null,
  ) => {
    if (hold !== kind || workspace !== P) return response;
    const json = response.json.bind(response);
    response.json = async () => {
      const body: unknown = await json();
      return new Promise((resolve) => {
        const release = () => {
          pending.delete(release);
          resolve(body);
        };
        pending.add(release);
      });
    };
    return response;
  };
  const seen: {
    path: string;
    method: string;
    workspace: string | null;
    filename: string | null;
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
      const workspace = new Headers(init?.headers).get("X-Deerflow-Workspace");
      const method = init?.method ?? "GET";
      const file =
        init?.body instanceof FormData ? init.body.get("file") : null;
      seen.push({
        path,
        method,
        workspace,
        filename: file instanceof File ? file.name : null,
      });
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
      const document = {
        id: "doc-1",
        name: path.includes("/project-2/")
          ? `project-2-${workspace}.txt`
          : `${workspace}.txt`,
        size_bytes: 12,
        sha256: "fixture",
        content_missing: false,
        source_thread_id: null,
        source_kind: null,
        source_name: null,
        created_at: "2026-10-15T00:00:00Z",
        updated_at: "2026-10-15T00:00:00Z",
      };
      if (path === "/api/projects/config")
        return Response.json({
          instructions_max_bytes: 8192,
          trash_retention_days: 30,
        });
      if (/^\/api\/projects\/[^/]+\/documents$/.test(path))
        return method === "GET"
          ? Response.json({
              documents: [document],
              total: 1,
              limit: 100,
              offset: 0,
            })
          : delayed(
              Response.json({ document, deduplicated: false }),
              "upload",
              workspace,
            );
      if (path.endsWith("/thread-files"))
        return Response.json({
          groups: [],
          next_offset: null,
          truncated: false,
        });
      if (path.endsWith("/content"))
        return new Response(`preview-${workspace}`, {
          headers: { "Content-Type": "text/plain" },
        });
      if (path.endsWith("/attach-to-thread/thread-1"))
        return delayed(
          Response.json({
            filename: document.name,
            size_bytes: 12,
            virtual_path: "/mnt/user-data/uploads/report.txt",
            artifact_url:
              "/api/threads/thread-1/artifacts/mnt/user-data/uploads/report.txt",
          }),
          "attach",
          workspace,
        );
      if (path.endsWith("/threads/search"))
        return Response.json([
          {
            thread_id: "thread-1",
            metadata: {},
            values: { title: "Report chat" },
            status: "idle",
            created_at: document.created_at,
            updated_at: document.updated_at,
          },
        ]);
      if (path === "/api/skills") return Response.json({ skills: [] });
      if (path === "/api/features") return Response.json({});
      if (path.endsWith("/uploads/limits"))
        return Response.json({
          max_files: 5,
          max_file_size: 1000,
          max_total_size: 5000,
        });
      if (path.endsWith("/uploads/list")) return Response.json({ files: [] });
      throw new Error(`Unexpected shelf request ${method} ${path}`);
    },
  );
  return {
    seen,
    hold: (kind: "attach" | "upload") => {
      hold = kind;
    },
    resume: () => {
      hold = null;
      for (const release of [...pending]) release();
    },
  };
}
function mount() {
  let control: WorkspaceContextValue | null = null;
  let cache: QueryClient | null = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  function Content() {
    cache = useQueryClient();
    const [mode, setMode] = useState("project");
    const [projectId, setProjectId] = useState("project-1");
    useEffect(() => {
      mocks.push.mockImplementation(() => setMode("composer"));
    }, []);
    const project = {
      id: projectId,
      name: projectId,
      instructions: "",
      presentation: {},
      status: "active" as const,
      created_at: "2026-10-15T00:00:00Z",
      updated_at: "2026-10-15T00:00:00Z",
    };
    return (
      <>
        <button onClick={() => setMode("composer")}>Open composer</button>
        <button onClick={() => setMode("project")}>Open project</button>
        <button onClick={() => setProjectId("project-2")}>Other project</button>
        {mode === "project" ? (
          <ProjectDocumentsSection
            project={project}
            threads={[{ thread_id: "thread-1", display_name: "Report chat" }]}
          />
        ) : (
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: true }}
          >
            <PromptInputProvider>
              <InputBox
                threadId="thread-1"
                status="ready"
                context={{ mode: "flash" } as never}
                canCreateRuns
                onSubmit={mocks.submit}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        )}
      </>
    );
  }
  const view = render(
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
              <Content />
            </WorkspaceReadyBoundary>
          </WorkspaceProvider>
        </I18nContext.Provider>
      </QueryClientProvider>
    </AuthProvider>,
  );
  return {
    view,
    cache: () => cache!,
    select: async (id: string) => {
      await act(async () => {
        expect(await control!.select(id)).toBe(true);
      });
    },
  };
}
afterEach(() => {
  for (const release of [...pending]) release();
  cleanup();
  sessionStorage.clear();
  rs.unstubAllGlobals();
  rs.clearAllMocks();
});
async function attach(app: ReturnType<typeof mount>, space: string) {
  await app.view.findByText(`${space}.txt`);
  fireEvent.click(app.view.getByRole("button", { name: /Attach to chat/ }));
  const dialog = await app.view.findByRole("dialog");
  fireEvent.click(
    await within(dialog).findByRole("button", { name: "Report chat" }),
  );
  await waitFor(() =>
    expect(
      app.view.getByTestId("project-attachment-chip").textContent,
    ).toContain(`${space}.txt`),
  );
}
async function send(app: ReturnType<typeof mount>) {
  const before = mocks.submit.mock.calls.length;
  const button = app.view.container.querySelector('button[type="submit"]');
  if (!(button instanceof HTMLButtonElement))
    throw new Error("Composer not mounted");
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(before + 1));
  const [, options] = mocks.submit.mock.calls.at(-1)!;
  await act(async () => {
    options?.onSent?.();
  });
  await waitFor(() =>
    expect(app.view.queryByTestId("project-attachment-chip")).toBeNull(),
  );
}
it("previews and hands shelf documents to the real composer within each workspace", async () => {
  const { seen } = fixture();
  stageProjectAttachment("thread-1", {
    filename: "legacy.txt",
    virtual_path: "/legacy",
    artifact_url: "/legacy",
    size_bytes: 1,
  });
  const app = mount();
  await app.view.findByText(`${P}.txt`);
  fireEvent.click(app.view.getByRole("button", { name: "Preview" }));
  const preview = await app.view.findByRole("dialog");
  await within(preview).findByText(`preview-${P}`);
  fireEvent.click(within(preview).getByRole("button", { name: "Close" }));
  const href = app.view
    .getByRole("link", { name: "Download" })
    .getAttribute("href")!;
  expect(new URL(href, location.href).searchParams.get("workspace_id")).toBe(P);
  await attach(app, P);
  expect(app.view.getAllByTestId("project-attachment-chip")).toHaveLength(1);
  await app.select(T);
  await app.view.findByText(`${T}.txt`);
  fireEvent.click(app.view.getByRole("button", { name: "Open composer" }));
  await waitFor(() =>
    expect(app.view.container.querySelector("textarea")).not.toBeNull(),
  );
  expect(app.view.queryByTestId("project-attachment-chip")).toBeNull();
  fireEvent.click(app.view.getByRole("button", { name: "Open project" }));
  await attach(app, T);
  await send(app);
  await app.select(P);
  await app.view.findByText(`${P}.txt`);
  fireEvent.click(app.view.getByRole("button", { name: "Open composer" }));
  await waitFor(() =>
    expect(
      app.view.getByTestId("project-attachment-chip").textContent,
    ).toContain(`${P}.txt`),
  );
  await send(app);
  expect(
    seen
      .filter((row) => row.path.endsWith("/attach-to-thread/thread-1"))
      .map((row) => row.workspace),
  ).toEqual([P, T]);
  expect(
    readProjectAttachments("thread-1").map((file) => file.filename),
  ).toEqual(["legacy.txt"]);
});

it("refuses late attach publication and old send callbacks while preserving each space's draft", async () => {
  const net = fixture();
  const app = mount();
  await attach(app, P);
  const before = mocks.submit.mock.calls.length;
  const submit = app.view.container.querySelector('button[type="submit"]');
  if (!(submit instanceof HTMLButtonElement))
    throw new Error("Composer missing");
  await waitFor(() => expect(submit.disabled).toBe(false));
  fireEvent.click(submit);
  await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(before + 1));
  const [, oldOptions] = mocks.submit.mock.calls.at(-1)!;
  fireEvent.click(app.view.getByRole("button", { name: "Open project" }));
  await app.view.findByText(`${P}.txt`);
  net.hold("attach");
  fireEvent.click(app.view.getByRole("button", { name: /Attach to chat/ }));
  const dialog = await app.view.findByRole("dialog");
  fireEvent.click(
    await within(dialog).findByRole("button", { name: "Report chat" }),
  );
  await waitFor(() => expect(pending.size).toBe(1));
  const oldMutation = app
    .cache()
    .getMutationCache()
    .getAll()
    .find((mutation) => mutation.state.status === "pending");
  expect(oldMutation).toBeDefined();
  await app.select(T);
  await attach(app, T);
  const pushes = mocks.push.mock.calls.length;
  const successes = mocks.success.mock.calls.length;
  await act(async () => {
    net.resume();
    oldOptions?.onSent?.();
  });
  await waitFor(() => expect(oldMutation!.state.status).toBe("error"));
  expect(oldMutation!.state.error).toMatchObject({ name: "AbortError" });
  expect(mocks.push).toHaveBeenCalledTimes(pushes);
  expect(mocks.success).toHaveBeenCalledTimes(successes);
  expect(mocks.error).not.toHaveBeenCalled();
  expect(app.view.getByTestId("project-attachment-chip").textContent).toContain(
    `${T}.txt`,
  );
  await send(app);
  await app.select(P);
  await app.view.findByText(`${P}.txt`);
  fireEvent.click(app.view.getByRole("button", { name: "Open composer" }));
  await waitFor(() =>
    expect(
      app.view.getByTestId("project-attachment-chip").textContent,
    ).toContain(`${P}.txt`),
  );
});
it("stops the old multi-file loop on same-space project navigation", async () => {
  const net = fixture();
  const app = mount();
  await app.view.findByText(`${P}.txt`);
  net.hold("upload");
  fireEvent.change(app.view.getByTestId("project-documents-upload-input"), {
    target: {
      files: [new File(["one"], "first.txt"), new File(["two"], "second.txt")],
    },
  });
  await waitFor(() => expect(pending.size).toBe(1));
  const oldMutation = app
    .cache()
    .getMutationCache()
    .getAll()
    .find((mutation) => mutation.state.status === "pending");
  expect(oldMutation).toBeDefined();
  fireEvent.click(app.view.getByRole("button", { name: "Other project" }));
  await app.view.findByText(`project-2-${P}.txt`);
  await act(async () => {
    net.resume();
  });
  await waitFor(() => expect(oldMutation!.state.status).toBe("success"));
  expect(
    net.seen
      .filter((row) => row.method === "POST" && row.path.endsWith("/documents"))
      .map((row) => [row.path, row.filename]),
  ).toEqual([["/api/projects/project-1/documents", "first.txt"]]);
  expect(mocks.error).not.toHaveBeenCalled();
  fireEvent.change(app.view.getByTestId("project-documents-upload-input"), {
    target: { files: [new File(["new"], "current.txt")] },
  });
  await waitFor(() =>
    expect(
      net.seen.some(
        (row) =>
          row.path === "/api/projects/project-2/documents" &&
          row.method === "POST" &&
          row.filename === "current.txt",
      ),
    ).toBe(true),
  );
});
