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
import { useState } from "react";

import ProjectPage from "@/app/workspace/projects/[id]/page";
import {
  PromptInputProvider,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarProvider } from "@/components/ui/sidebar";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import { referenceToken } from "@/components/workspace/mentions/inline-references";
import { ThreadContext } from "@/components/workspace/messages/context";
import { NewProjectDialog } from "@/components/workspace/move-to-project-menu";
import { ProjectsSection } from "@/components/workspace/projects-section";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  createWorkspaceComposerDraftStorage,
  buildComposerDraftKey,
  getSessionComposerDraftStorage,
  readComposerDraft,
  writeComposerDraft,
} from "@/core/threads/composer-draft";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

const mocks = rs.hoisted(() => ({
  push: rs.fn(),
  error: rs.fn(),
  submit:
    rs.fn<
      (
        message: PromptInputMessage,
        options?: InputBoxSubmitOptions,
      ) => void | Promise<void>
    >(),
  skills: [],
}));
rs.mock("next/navigation", () => ({
  useParams: () => ({ id: "project-1" }),
  useRouter: () => ({ push: mocks.push, replace: rs.fn() }),
  usePathname: () => "/workspace/projects/project-1",
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("sonner", () => ({
  toast: Object.assign(rs.fn(), {
    error: mocks.error,
    success: rs.fn(),
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
rs.mock("@/core/skills/hooks", () => ({
  useSkills: () => ({
    skills: mocks.skills,
    isLoading: false,
    isFetching: false,
    refetch: rs.fn(),
  }),
}));
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => null,
  WorkspaceBody: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));
rs.mock("@/components/workspace/projects/project-documents-section", () => ({
  ProjectDocumentsSection: () => null,
}));
rs.mock("@/components/workspace/projects/project-threads-section", () => ({
  ProjectThreadsSection: () => null,
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
function fixture() {
  type Row = {
    id: string;
    name: string;
    instructions: string;
    presentation: Record<string, unknown>;
    status: string;
    created_at: string;
    updated_at: string;
  };
  const data = new Map<string, Map<string, Row>>();
  let next = 0;
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
        location.href,
      );
      const path = url.pathname;
      const workspace = new Headers(init?.headers).get("X-Deerflow-Workspace");
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : {};
      seen.push({ path, method, workspace, body });
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
      let rows = data.get(workspace ?? "legacy");
      if (!rows) {
        rows = new Map();
        rows.set("project-1", {
          id: "project-1",
          name: `${workspace} Project`,
          instructions: "Initial",
          presentation: {},
          status: "active",
          created_at: "2026-10-15T00:00:00Z",
          updated_at: "2026-10-15T00:00:00Z",
        });
        data.set(workspace ?? "legacy", rows);
      }
      if (path === "/api/projects/config")
        return Response.json({
          instructions_max_bytes: 8192,
          trash_retention_days: 30,
        });
      if (path === "/api/projects") {
        if (method === "GET")
          return Response.json({
            projects: [...rows.values()].filter(
              (row) =>
                !url.searchParams.get("status") ||
                row.status === url.searchParams.get("status"),
            ),
          });
        const row = {
          id: `created-${++next}`,
          name: String(body.name),
          instructions:
            typeof body.instructions === "string" ? body.instructions : "",
          presentation: {},
          status: "active",
          created_at: "2026-10-15T00:00:00Z",
          updated_at: "2026-10-15T00:00:00Z",
        };
        rows.set(row.id, row);
        return Response.json(row, { status: 201 });
      }
      if (path.endsWith("/threads") && path.startsWith("/api/projects/"))
        return Response.json([]);
      if (path.startsWith("/api/projects/")) {
        const id = path.split("/")[3]!;
        const row = rows.get(id);
        if (!row)
          return Response.json({ detail: "Not found" }, { status: 404 });
        if (method === "DELETE") {
          rows.delete(id);
          return new Response(null, { status: 204 });
        }
        if (path.endsWith("/archive")) row.status = "archived";
        else if (path.endsWith("/restore")) row.status = "active";
        else if (method === "PATCH") Object.assign(row, body);
        return Response.json(row);
      }
      if (path === "/api/threads/thread-1/move")
        return Response.json({
          thread_id: "thread-1",
          metadata: { deerflow_project_id: body.project_id },
          created_at: "",
          updated_at: "",
          status: "idle",
        });
      if (path === "/api/features")
        return Response.json({
          agents_api: { enabled: false },
          conversation_references: { enabled: true, max_references: 5 },
        });
      if (path.endsWith("/uploads/limits"))
        return Response.json({
          max_files: 5,
          max_file_size: 1000,
          max_total_size: 5000,
        });
      if (path.endsWith("/uploads/list")) return Response.json({ files: [] });
      throw new Error(`Unexpected workflow request ${method} ${path}`);
    },
  );
  return { seen };
}
function mount(mode: "page" | "composer") {
  let control: WorkspaceContextValue | null = null;
  let cache: QueryClient | null = null;
  let lifetime: ReturnType<typeof useWorkspaceLifetime> = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  function Content() {
    cache = useQueryClient();
    lifetime = useWorkspaceLifetime();
    const [open, setOpen] = useState(false);
    return mode === "page" ? (
      <SidebarProvider>
        <ProjectsSection />
        <button onClick={() => setOpen(true)}>Open mover</button>
        <NewProjectDialog
          thread={
            {
              thread_id: "thread-1",
              metadata: {},
              values: { title: "Chat" },
            } as never
          }
          open={open}
          onOpenChange={setOpen}
        />
        <ProjectPage />
      </SidebarProvider>
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
    lifetime: () => lifetime!,
    select: async (id: string) => {
      await act(async () => {
        expect(await control!.select(id)).toBe(true);
      });
    },
  };
}
const pending = new Set<() => void>();
afterEach(() => {
  for (const release of [...pending]) release();
  cleanup();
  mocks.submit.mockReset();
  sessionStorage.clear();
  rs.unstubAllGlobals();
  rs.clearAllMocks();
});
it("uses the native project page, sidebar create and create-then-move workflow in each space", async () => {
  const net = fixture();
  const app = mount("page");
  for (const space of [P, T]) {
    if (space === T) await app.select(T);
    await app.view.findByRole("heading", { name: `${space} Project` });
    fireEvent.mouseDown(app.view.getByRole("tab", { name: "Instructions" }));
    const instructions = app.view.getByRole("textbox", {
      name: "Instructions",
    });
    fireEvent.change(instructions, { target: { value: `Sources ${space}` } });
    fireEvent.click(app.view.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(
        net.seen.some(
          (row) =>
            row.workspace === space &&
            row.method === "PATCH" &&
            (row.body as { instructions?: string }).instructions ===
              `Sources ${space}`,
        ),
      ).toBe(true),
    );
    fireEvent.mouseDown(app.view.getByRole("tab", { name: "Settings" }));
    fireEvent.change(app.view.getByLabelText("Project name"), {
      target: { value: `Renamed ${space}` },
    });
    fireEvent.click(app.view.getByRole("button", { name: "Save" }));
    await app.view.findByRole("heading", { name: `Renamed ${space}` });
    fireEvent.click(app.view.getByRole("button", { name: "Archive" }));
    fireEvent.click(await app.view.findByRole("button", { name: "Restore" }));
    await app.view.findByRole("button", { name: "Archive" });
    fireEvent.click(app.view.getByTestId("projects-new-project-button"));
    let dialog = await app.view.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText("Project name"), {
      target: { value: `Sidebar ${space}` },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(app.view.queryByRole("dialog")).toBeNull());
    fireEvent.click(app.view.getByRole("button", { name: "Open mover" }));
    dialog = await app.view.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText("Project name"), {
      target: { value: `Moved ${space}` },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(
        net.seen.some(
          (row) => row.workspace === space && row.path.endsWith("/move"),
        ),
      ).toBe(true),
    );
    fireEvent.click(app.view.getByRole("button", { name: "Delete project" }));
    dialog = await app.view.findByRole("dialog");
    const before = mocks.push.mock.calls.length;
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledTimes(before + 1));
  }
  expect(
    net.seen
      .filter(
        (row) =>
          row.path.startsWith("/api/projects") || row.path.endsWith("/move"),
      )
      .every((row) => row.workspace === P || row.workspace === T),
  ).toBe(true);
  expect(mocks.error).not.toHaveBeenCalled();
});
it("keeps real composer drafts separate and preserves the last input across immediate workspace switches", async () => {
  fixture();
  const legacyKey = buildComposerDraftKey({
    userId: "alice",
    threadId: "thread-1",
  });
  const storage = getSessionComposerDraftStorage();
  writeComposerDraft(storage, legacyKey, {
    text: "Legacy personal notes",
    skillName: null,
  });
  const app = mount("composer");
  const personal = await app.view.findByRole("textbox");
  expect((personal as HTMLTextAreaElement).value).toBe("");
  fireEvent.change(personal, { target: { value: "Personal notes" } });
  await app.select(T);
  const team = await app.view.findByRole("textbox");
  expect((team as HTMLTextAreaElement).value).toBe("");
  fireEvent.change(team, { target: { value: "Team notes" } });
  await app.select(P);
  await waitFor(() =>
    expect((app.view.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "Personal notes",
    ),
  );
  await app.select(T);
  await waitFor(() =>
    expect((app.view.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "Team notes",
    ),
  );
  expect(readComposerDraft(storage, legacyKey)?.text).toBe(
    "Legacy personal notes",
  );
});

it("rejects expired or foreign draft access and preserves replacements after a late onSent", async () => {
  fixture();
  const app = mount("composer");
  const editor = await app.view.findByRole("textbox");
  const life = app.lifetime();
  const oldStore = createWorkspaceComposerDraftStorage(life.scope);
  const personalKey = buildComposerDraftKey({
    userId: "alice",
    workspaceId: P,
    threadId: "thread-1",
  });
  const teamKey = buildComposerDraftKey({
    userId: "alice",
    workspaceId: T,
    threadId: "thread-1",
  });
  let release!: () => void;
  const submitted = new Promise<void>((resolve) => {
    release = () => {
      pending.delete(release);
      resolve();
    };
    pending.add(release);
  });
  mocks.submit.mockImplementation(() => submitted);
  fireEvent.change(editor, { target: { value: "Personal sent" } });
  const button = app.view.container.querySelector('button[type="submit"]');
  if (!(button instanceof HTMLButtonElement))
    throw new Error("Composer missing");
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));
  const [, oldOptions] = mocks.submit.mock.calls[0]!;
  await app.select(T);
  const team = await app.view.findByRole("textbox");
  fireEvent.change(team, { target: { value: "Team replacement" } });
  expect(oldStore.getItem(personalKey)).toBeNull();
  expect(oldStore.getItem(teamKey)).toBeNull();
  await app.select(P);
  await waitFor(() =>
    expect((app.view.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "Personal sent",
    ),
  );
  fireEvent.change(app.view.getByRole("textbox"), {
    target: { value: "Personal replacement" },
  });
  const currentStore = createWorkspaceComposerDraftStorage(
    app.lifetime().scope,
  );
  oldStore.setItem(personalKey, "stale");
  oldStore.removeItem(personalKey);
  currentStore.setItem(teamKey, "foreign");
  currentStore.removeItem(teamKey);
  await act(async () => {
    oldOptions?.onSent?.();
    release();
    await submitted;
  });
  expect((app.view.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
    "Personal replacement",
  );
  expect(readComposerDraft(currentStore, personalKey)?.text).toBe(
    "Personal replacement",
  );
  expect(currentStore.getItem(teamKey)).toBeNull();
  expect(
    readComposerDraft(getSessionComposerDraftStorage(), teamKey)?.text,
  ).toBe("Team replacement");
  const references = [
    { threadId: "source-1", title: "Personal source", agentName: "writer" },
  ];
  writeComposerDraft(currentStore, personalKey, {
    text:
      referenceToken("conversation", "source-1", "Personal source") + " notes",
    skillName: null,
    conversationReferences: references,
  });
  expect(
    readComposerDraft(currentStore, personalKey)?.conversationReferences,
  ).toEqual(references);
  await app.select(T);
  await waitFor(() =>
    expect((app.view.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "Team replacement",
    ),
  );
  expect(app.view.queryByTestId("conversation-reference-chip")).toBeNull();
  await app.select(P);
  const chip = await app.view.findByTestId("conversation-reference-chip");
  expect(chip.textContent).toContain("Personal source");
  expect(
    readComposerDraft(
      createWorkspaceComposerDraftStorage(app.lifetime().scope),
      personalKey,
    )?.conversationReferences,
  ).toEqual(references);
});
