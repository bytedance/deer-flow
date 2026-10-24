import { afterEach, expect, it, rs } from "@rstest/core";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  waitFor,
} from "@testing-library/react";
import { useEffect, useRef } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { ThreadContext } from "@/components/workspace/messages/context";
import {
  SidecarProvider,
  useSidecar,
} from "@/components/workspace/sidecar/context";
import { SidecarPanel } from "@/components/workspace/sidecar/sidecar-panel";
import type { getAPIClient } from "@/core/api/api-client";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { createSidecarThread } from "@/core/sidecar/api";
import { SubtasksProvider } from "@/core/tasks/context";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

const mocks = rs.hoisted(() => ({ error: rs.fn(), success: rs.fn() }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("sonner", () => ({
  toast: Object.assign(rs.fn(), {
    error: mocks.error,
    warning: rs.fn(),
    success: mocks.success,
  }),
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ models: [], tokenUsageEnabled: false, isLoading: false }),
}));
// Real panel/provider/composer/thread hooks and SDK/REST clients. Only the
// React SDK adapter is doubled; submit uses the real SDK SSE transport/parser.
rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: {
    client: ReturnType<typeof getAPIClient>;
    assistantId: string;
  }) => ({
    isLoading: false,
    messages: [],
    values: { artifacts: [], messages: [], title: "", todos: [] },
    stop: rs.fn(),
    joinStream: rs.fn(),
    submit: async (
      input: Record<string, unknown>,
      args: { threadId: string; context?: Record<string, unknown> },
    ) => {
      for await (const frame of options.client.runs.stream(
        args.threadId,
        options.assistantId,
        { input, context: args.context, streamMode: ["values"] },
      )) {
        void frame;
      }
    },
  }),
}));
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const pendingReplies = new Set<() => void>();
const observedRequests: Promise<unknown>[] = [];
function fixture() {
  let holdCreate = false;
  let holdDelete = false;
  let releaseCreate: (() => void) | undefined;
  let releaseDelete: (() => void) | undefined;
  const seen: {
    path: string;
    method: string;
    workspace: string | null;
    body: unknown;
  }[] = [];
  const rows = new Map<
    string,
    {
      thread_id: string;
      metadata: Record<string, unknown>;
      [key: string]: unknown;
    }
  >();
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
      const requestBody =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as { metadata?: Record<string, unknown> })
          : {};
      seen.push({ path, method, workspace, body: requestBody });
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
      if (path.endsWith("/uploads/limits"))
        return Response.json({
          max_files: 5,
          max_file_size: 1000,
          max_total_size: 5000,
        });
      if (path.endsWith("/threads/search")) {
        const row = workspace ? rows.get(workspace) : undefined;
        return Response.json(
          row &&
            row.metadata.parent_thread_id ===
              requestBody.metadata?.parent_thread_id
            ? [row]
            : [],
        );
      }
      if (path === "/api/threads" && method === "POST") {
        const body =
          typeof init?.body === "string"
            ? (JSON.parse(init.body) as { metadata?: Record<string, unknown> })
            : {};
        const row = {
          thread_id: `sidecar-${workspace ?? "legacy"}`,
          metadata: body.metadata ?? {},
          values: { title: workspace, messages: [], artifacts: [] },
          status: "idle",
          created_at: "2026-10-15T00:00:00Z",
          updated_at: "2026-10-15T00:00:00Z",
          interrupts: {},
        };
        if (workspace) rows.set(workspace, row);
        const response = Response.json(row);
        if (holdCreate && workspace === P)
          response.json = () =>
            new Promise((resolve) => {
              const release = () => {
                pendingReplies.delete(release);
                resolve(row);
              };
              releaseCreate = release;
              pendingReplies.add(release);
            });
        return response;
      }
      if (method === "DELETE" && path.includes("/threads/sidecar-")) {
        if (workspace) rows.delete(workspace);
        const response = new Response(null, { status: 204 });
        if (holdDelete && workspace === P)
          return new Promise<Response>((resolve) => {
            const release = () => {
              pendingReplies.delete(release);
              resolve(response);
            };
            releaseDelete = release;
            pendingReplies.add(release);
          });
        return response;
      }
      if (path.endsWith("/messages/page"))
        return Response.json({
          data: [],
          has_more: false,
          next_before_seq: null,
        });
      if (path.endsWith("/runs/stream"))
        return new Response("event: end\ndata: null\n\n", {
          headers: { "Content-Type": "text/event-stream" },
        });
      if (path.endsWith("/runs")) return Response.json([]);
      if (path.includes("/threads/sidecar-"))
        return Response.json(
          rows.get(workspace ?? "") ?? {
            thread_id: "sidecar-legacy",
            metadata: {},
            values: { title: "", messages: [], artifacts: [] },
            status: "idle",
            interrupts: {},
          },
        );
      throw new Error(`Unexpected sidecar request ${method} ${path}`);
    },
  );
  return {
    seen,
    holdCreate: () => {
      holdCreate = true;
    },
    getCreateRelease: () => releaseCreate,
    holdDelete: () => {
      holdDelete = true;
    },
    getDeleteRelease: () => releaseDelete,
  };
}
function SeedReferences() {
  const sidecar = useSidecar();
  const lifetime = useWorkspaceLifetime();
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;
    sidecar.openContext({
      type: "referenced_message",
      label: "Earlier answer",
      role: "assistant",
      content: `Evidence ${lifetime!.scope.workspaceId}`,
    });
  }, [lifetime, sidecar]);
  return null;
}
function mount() {
  let control: WorkspaceContextValue | null = null;
  let cache: QueryClient | null = null;
  function CacheProbe() {
    cache = useQueryClient();
    return null;
  }
  function Controls() {
    control = useWorkspaceContext();
    return null;
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
              <CacheProbe />
              <SubtasksProvider>
                <ThreadContext.Provider
                  value={{ thread: { messages: [] } as never, isMock: false }}
                >
                  <SidecarProvider
                    parentThreadId="parent-1"
                    context={DEFAULT_LOCAL_SETTINGS.context}
                  >
                    <SeedReferences />
                    <SidecarPanel />
                  </SidecarProvider>
                </ThreadContext.Provider>
              </SubtasksProvider>
            </WorkspaceReadyBoundary>
          </WorkspaceProvider>
        </I18nContext.Provider>
      </QueryClientProvider>
    </AuthProvider>,
  );
  return {
    view,
    lifetime: () => control!.state.active!,
    cache: () => cache!,
    select: async () => {
      await act(async () => {
        expect(await control!.select(T)).toBe(true);
      });
    },
  };
}
afterEach(async () => {
  await act(async () => {
    for (const release of [...pendingReplies]) release();
    cleanup();
    await Promise.allSettled(observedRequests);
  });
  pendingReplies.clear();
  observedRequests.length = 0;
  rs.unstubAllGlobals();
  rs.clearAllMocks();
  sessionStorage.clear();
});
async function submitDraft(container: HTMLElement, text: string) {
  await waitFor(() =>
    expect(container.querySelector("textarea")).not.toBeNull(),
  );
  const composer = container.querySelector("textarea");
  if (!(composer instanceof HTMLTextAreaElement))
    throw new Error("Missing sidecar composer");
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: text } });
  await act(async () => {
    fireEvent.submit(composer.closest("form")!);
  });
  return composer;
}

it("restores creates and sends real sidecar references through personal and team clients", async () => {
  const server = fixture();
  const { view, select } = mount();
  for (const workspace of [P, T]) {
    if (workspace === T) await select();
    const composer = await view.findByRole("textbox");
    if (!(composer instanceof HTMLTextAreaElement)) {
      throw new Error("Missing sidecar composer");
    }
    await waitFor(() => expect(composer.disabled).toBe(false));
    fireEvent.change(composer, { target: { value: `Question ${workspace}` } });
    await act(async () => {
      fireEvent.submit(composer.closest("form")!);
    });
    await waitFor(() =>
      expect(
        server.seen.filter((row) => row.path.endsWith("/runs/stream")),
      ).toHaveLength(workspace === P ? 1 : 2),
    );
    await waitFor(() => expect(composer.value).toBe(""));
  }
  const lookups = server.seen.filter((row) =>
    row.path.endsWith("/threads/search"),
  );
  expect(lookups.length).toBeGreaterThanOrEqual(2);
  expect(
    lookups.every((row) => row.workspace === P || row.workspace === T),
  ).toBe(true);
  expect(
    server.seen
      .filter((row) => row.path === "/api/threads" && row.method === "POST")
      .map((row) => row.workspace),
  ).toEqual([P, T]);
  const streams = server.seen.filter((row) =>
    row.path.endsWith("/runs/stream"),
  );
  expect(streams.map((row) => row.workspace)).toEqual([P, T]);
  expect(JSON.stringify(streams[0]?.body)).toContain(`Evidence ${P}`);
  expect(JSON.stringify(streams[1]?.body)).toContain(`Evidence ${T}`);
  expect(JSON.stringify(streams[1]?.body)).not.toContain(`Evidence ${P}`);
  expect(mocks.error).not.toHaveBeenCalled();
  fireEvent.click(view.getByTestId("sidecar-delete-button"));
  fireEvent.click(await view.findByTestId("sidecar-delete-confirm-button"));
  await waitFor(() => expect(mocks.success).toHaveBeenCalledTimes(1));
  expect(
    server.seen
      .filter((row) => row.method === "DELETE")
      .map((row) => row.workspace),
  ).toEqual([T]);
});

it("creates a new team sidecar independently while a personal create is still decoding", async () => {
  const server = fixture();
  const page = mount();
  const { view, select } = page;
  server.holdCreate();
  await submitDraft(view.container, "Personal pending question");
  await waitFor(() => expect(server.getCreateRelease()).toBeDefined());
  // Join the already pending native API create using the exact same client.
  // This also verifies same-lifetime dedup without replacing the implementation.
  const lifetime = page.lifetime();
  const oldSubmit = createSidecarThread(
    {
      parentThreadId: "parent-1",
      context: {
        type: "referenced_message",
        label: "join",
        content: "join",
        role: "assistant",
      },
    },
    { rest: lifetime.rest, signal: lifetime.scope.signal },
  ).catch((error: unknown) => error);
  observedRequests.push(oldSubmit);
  expect(
    server.seen.filter(
      (row) => row.path === "/api/threads" && row.method === "POST",
    ),
  ).toHaveLength(1);
  await select();
  const composer = await submitDraft(view.container, "Team question");
  await waitFor(() =>
    expect(
      server.seen.filter(
        (row) => row.path === "/api/threads" && row.method === "POST",
      ),
    ).toHaveLength(2),
  );
  await waitFor(() => expect(composer.value).toBe(""));
  await act(async () => {
    server.getCreateRelease()!();
    await oldSubmit;
  });
  expect(await oldSubmit).toMatchObject({ name: "AbortError" });
  const streams = server.seen.filter((row) =>
    row.path.endsWith("/runs/stream"),
  );
  expect(streams.map((row) => row.workspace)).toEqual([T]);
  expect(JSON.stringify(streams[0]?.body)).toContain(`Evidence ${T}`);
  expect(JSON.stringify(streams[0]?.body)).not.toContain(`Evidence ${P}`);
  expect(mocks.error).not.toHaveBeenCalled();
});

it("keeps late native sidecar deletion feedback out of the next workspace", async () => {
  const server = fixture();
  const page = mount();
  const { view, select } = page;
  const personalComposer = await submitDraft(
    view.container,
    "Create personal sidecar",
  );
  await waitFor(() => expect(personalComposer.value).toBe(""));
  server.holdDelete();
  fireEvent.click(view.getByTestId("sidecar-delete-button"));
  fireEvent.click(await view.findByTestId("sidecar-delete-confirm-button"));
  await waitFor(() => expect(server.getDeleteRelease()).toBeDefined());
  const oldDelete = page
    .cache()
    .getMutationCache()
    .getAll()
    .find((mutation) => mutation.state.status === "pending")!;
  expect(oldDelete).toBeDefined();
  await select();
  await waitFor(() =>
    expect(view.container.querySelector("textarea")).not.toBeNull(),
  );
  const teamComposer = view.container.querySelector("textarea")!;
  fireEvent.change(teamComposer, { target: { value: "New team draft" } });
  await act(async () => {
    server.getDeleteRelease()!();
  });
  await waitFor(() => expect(oldDelete.state.status).toBe("error"));
  expect(oldDelete.state.error).toMatchObject({ name: "AbortError" });
  expect(mocks.error).not.toHaveBeenCalled();
  expect(mocks.success).not.toHaveBeenCalled();
  expect(teamComposer.value).toBe("New team draft");
  expect(
    server.seen
      .filter((row) => row.method === "DELETE")
      .map((row) => row.workspace),
  ).toEqual([P]);
});
