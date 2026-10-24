import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import type { getAPIClient } from "@/core/api/api-client";
import { reconnectRunStorageKey } from "@/core/api/api-client";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { SubtasksProvider } from "@/core/tasks/context";
import {
  useThreadMetadata,
  useThreadStream,
  useThreadTokenUsage,
} from "@/core/threads/hooks";
import type { AgentThreadState } from "@/core/threads/types";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

type Storage = {
  getItem(key: `lg:stream:${string}`): string | null;
  setItem(key: `lg:stream:${string}`, value: string): void;
  removeItem(key: `lg:stream:${string}`): void;
};
type StreamOptions = {
  client: ReturnType<typeof getAPIClient>;
  assistantId: string;
  reconnectOnMount: boolean | (() => Storage);
  onCreated(meta: { thread_id: string; run_id: string }): void;
  onCustomEvent(event: unknown): void;
  onError(error: Error): void;
  onFinish(state: { values: AgentThreadState }): void;
};
const mocks = rs.hoisted(() => ({
  latest: null as StreamOptions | null,
  error: rs.fn(),
  warning: rs.fn(),
  notice: rs.fn(),
  start: rs.fn(),
  finish: rs.fn(),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace",
}));
rs.mock("sonner", () => ({
  toast: Object.assign(mocks.notice, {
    error: mocks.error,
    warning: mocks.warning,
  }),
}));
// Only the React SDK adapter is doubled. The source hook, confirmed Context,
// REST/SDK clients, native Request/Response and SDK stream parser are real.
rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: StreamOptions) => {
    mocks.latest = options;
    return {
      isLoading: false,
      messages: [],
      values: { artifacts: [], messages: [], title: "", todos: [] },
      stop: rs.fn(),
      joinStream: rs.fn(),
      submit: async (
        input: Record<string, unknown>,
        args: { threadId: string; context?: Record<string, unknown> },
      ) => {
        for await (const part of options.client.runs.stream(
          args.threadId,
          options.assistantId,
          { input, context: args.context, streamMode: ["values"] },
        )) {
          void part;
        }
      },
    };
  },
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
    workspace: string | null;
    method: string;
    body?: BodyInit | null;
  }[] = [];
  let delay: "upload" | "blob" | "replay" | null = null;
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
      if (typeof input === "string" && input === "blob:report") {
        expect(workspace).toBeNull();
        if (delay === "blob")
          return new Promise<Response>((resolve) => {
            release = () => resolve(new Response("report"));
          });
        return new Response("report");
      }
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
      if (path.endsWith("/messages/page"))
        return Response.json({
          data: [
            {
              seq: 1,
              run_id: "history",
              content: {
                type: "human",
                id: "history",
                content: workspace ?? "unscoped",
              },
              metadata: { caller: "lead_agent" },
              created_at: "2026-10-14T00:00:00Z",
            },
          ],
          has_more: false,
          next_before_seq: null,
        });
      if (path.endsWith("/token-usage"))
        return Response.json({
          thread_id: "thread-1",
          total_tokens: workspace === P ? 11 : workspace === T ? 22 : 0,
        });
      if (path.endsWith("/prepare")) {
        const body = {
          input: {
            messages: [{ type: "human", id: "replacement", content: "Edited" }],
          },
          checkpoint: { checkpoint_ns: "", checkpoint_id: "checkpoint" },
          metadata: {},
          target_run_id: "history",
          replacement_human_message_id: "replacement",
          source_message_ids: ["history"],
        };
        const response = Response.json(body);
        if (delay === "replay")
          response.json = () =>
            new Promise((resolve) => {
              release = () => resolve(body);
            });
        return response;
      }
      if (path.endsWith("/runs/stream"))
        return new Response("event: end\ndata: null\n\n", {
          headers: { "Content-Type": "text/event-stream" },
        });
      if (path.endsWith("/runs")) return Response.json([]);
      if (path.endsWith("/uploads")) {
        const body = {
          success: true,
          files: [
            {
              filename: "report.txt",
              size: 6,
              virtual_path: "/mnt/user-data/uploads/report.txt",
            },
          ],
          message: "ok",
          skipped_files: [],
        };
        const response = Response.json(body);
        if (delay === "upload")
          response.json = () =>
            new Promise((resolve) => {
              release = () => resolve(body);
            });
        return response;
      }
      if (path.endsWith("/threads/thread-1"))
        return Response.json({
          thread_id: "thread-1",
          status: "idle",
          values: { title: workspace, messages: [], artifacts: [] },
          metadata: {},
          interrupts: {},
        });
      throw new Error(`Unexpected chat request ${path}`);
    },
  );
  return {
    seen,
    delay: (value: typeof delay) => {
      delay = value;
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
      chat: useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
        onStart: mocks.start,
        onFinish: mocks.finish,
      }),
      metadata: useThreadMetadata("thread-1"),
      usage: useThreadTokenUsage("thread-1"),
    }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <StrictMode>
          <AuthProvider initialUser={user}>
            <QueryClientProvider>
              <I18nContext.Provider
                value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
              >
                <WorkspaceProvider enabled>
                  <Controls />
                  <WorkspaceReadyBoundary>
                    <SubtasksProvider>{children}</SubtasksProvider>
                  </WorkspaceReadyBoundary>
                </WorkspaceProvider>
              </I18nContext.Provider>
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
    lifetime: () => control!.state.active!,
  };
}
function attachment(withFile = true) {
  return {
    text: "Research this report",
    files: [
      {
        type: "file" as const,
        url: "blob:report",
        mediaType: "text/plain",
        filename: "report.txt",
        ...(withFile ? { file: new File(["report"], "report.txt") } : {}),
      },
    ],
  };
}
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  rs.clearAllMocks();
  sessionStorage.clear();
});

it("reads native thread history/metadata/usage and uploads/submits through each confirmed space", async () => {
  const server = fixture();
  const { view, select } = mount();
  await waitFor(() =>
    expect(view.result.current.metadata.data?.values.title).toBe(P),
  );
  await waitFor(() =>
    expect(view.result.current.usage.data?.total_tokens).toBe(11),
  );
  await waitFor(() =>
    expect(
      view.result.current.chat.thread.messages.some(
        (message) => message.content === P,
      ),
    ).toBe(true),
  );
  const onSent = rs.fn();
  await act(async () => {
    await view.result.current.chat.sendMessage(
      "thread-1",
      attachment(),
      undefined,
      { onSent },
    );
  });
  expect(onSent).toHaveBeenCalledTimes(1);
  await select();
  await waitFor(() =>
    expect(view.result.current.metadata.data?.values.title).toBe(T),
  );
  await waitFor(() =>
    expect(view.result.current.usage.data?.total_tokens).toBe(22),
  );
  await waitFor(() =>
    expect(
      view.result.current.chat.thread.messages.some(
        (message) => message.content === T,
      ),
    ).toBe(true),
  );
  expect(
    view.result.current.chat.thread.messages.some(
      (message) => message.content === P,
    ),
  ).toBe(false);
  await act(async () => {
    await view.result.current.chat.sendMessage("thread-1", attachment());
  });
  const submissions = server.seen.filter((row) =>
    row.path.endsWith("/runs/stream"),
  );
  expect(submissions.map((row) => row.workspace)).toEqual([P, T]);
  expect(
    submissions.every(
      (row) =>
        typeof row.body === "string" &&
        (JSON.parse(row.body) as { on_disconnect?: string }).on_disconnect ===
          "continue",
    ),
  ).toBe(true);
  expect(
    server.seen
      .filter((row) => row.path.includes("/threads/"))
      .every((row) => row.workspace === P || row.workspace === T),
  ).toBe(true);
});

it("refuses late decoded uploads and old stream callbacks without submitting, notifying or cancelling Runs", async () => {
  const server = fixture();
  const { view, select } = mount();
  await waitFor(() =>
    expect(view.result.current.metadata.isSuccess).toBe(true),
  );
  const callbacks = mocks.latest!;
  server.delay("upload");
  const onSent = rs.fn();
  let pending!: Promise<unknown>;
  act(() => {
    pending = view.result.current.chat
      .sendMessage("thread-1", attachment(), undefined, { onSent })
      .catch((error: unknown) => error);
  });
  await waitFor(() => expect(server.getRelease()).toBeDefined());
  await select();
  mocks.start.mockClear();
  mocks.finish.mockClear();
  mocks.error.mockClear();
  mocks.notice.mockClear();
  await act(async () => {
    server.getRelease()!();
  });
  expect(await pending).toMatchObject({ name: "AbortError" });
  act(() => {
    callbacks.onCreated({ thread_id: "thread-1", run_id: "stale" });
    callbacks.onCustomEvent({ type: "llm_retry", message: "old retry" });
    callbacks.onError(new Error("old stream error"));
    callbacks.onFinish({
      values: {
        messages: [],
        artifacts: [],
        title: "old",
        todos: [],
      } as AgentThreadState,
    });
  });
  expect(onSent).not.toHaveBeenCalled();
  expect(mocks.start).not.toHaveBeenCalled();
  expect(mocks.finish).not.toHaveBeenCalled();
  expect(mocks.error).not.toHaveBeenCalled();
  expect(mocks.notice).not.toHaveBeenCalled();
  expect(
    server.seen.some(
      (row) =>
        row.path.endsWith("/runs/stream") || row.path.includes("/cancel"),
    ),
  ).toBe(false);
});

it("fences file conversion and scopes the actual React SDK reconnect storage adapter", async () => {
  const server = fixture();
  sessionStorage.setItem("lg:stream:thread-1", "legacy-run");
  const { view, select, lifetime } = mount();
  await waitFor(() =>
    expect(view.result.current.metadata.isSuccess).toBe(true),
  );
  expect(typeof mocks.latest!.reconnectOnMount).toBe("function");
  const storage = (mocks.latest!.reconnectOnMount as () => Storage)();
  expect(storage.getItem("lg:stream:thread-1")).toBeNull();
  storage.setItem("lg:stream:thread-1", "personal-run");
  expect(
    sessionStorage.getItem(
      reconnectRunStorageKey("thread-1", lifetime().scope),
    ),
  ).toBe("personal-run");
  const retainedSend = view.result.current.chat.sendMessage;
  server.delay("blob");
  const onSent = rs.fn();
  let pending!: Promise<unknown>;
  act(() => {
    pending = retainedSend("thread-1", attachment(false), undefined, {
      onSent,
    }).catch((error: unknown) => error);
  });
  await waitFor(() => expect(server.getRelease()).toBeDefined());
  await select();
  const teamStorage = (mocks.latest!.reconnectOnMount as () => Storage)();
  teamStorage.setItem("lg:stream:thread-1", "team-run");
  storage.removeItem("lg:stream:thread-1");
  storage.setItem("lg:stream:thread-1", "stale-run");
  expect(storage.getItem("lg:stream:thread-1")).toBeNull();
  expect(teamStorage.getItem("lg:stream:thread-1")).toBe("team-run");
  expect(sessionStorage.getItem("lg:stream:thread-1")).toBe("legacy-run");
  await act(async () => {
    server.getRelease()!();
  });
  expect(await pending).toMatchObject({ name: "AbortError" });
  await expect(
    retainedSend("thread-1", { text: "old callback", files: [] }),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(onSent).not.toHaveBeenCalled();
  expect(
    server.seen.some(
      (row) =>
        row.path.endsWith("/uploads") || row.path.endsWith("/runs/stream"),
    ),
  ).toBe(false);
});

it("prepares regenerate and edit replay in the confirmed space before submitting", async () => {
  const server = fixture();
  const { view, select } = mount();
  await waitFor(() =>
    expect(view.result.current.metadata.isSuccess).toBe(true),
  );
  await act(async () => {
    expect(
      await view.result.current.chat.regenerateMessage("thread-1", "history"),
    ).toBe(true);
  });
  await select();
  await waitFor(() =>
    expect(view.result.current.metadata.data?.values.title).toBe(T),
  );
  await act(async () => {
    expect(
      await view.result.current.chat.editAndRegenerateMessage(
        "thread-1",
        "history",
        "Edited",
      ),
    ).toBe(true);
  });
  expect(
    server.seen
      .filter((row) => row.path.endsWith("/prepare"))
      .map((row) => row.workspace),
  ).toEqual([P, T]);
  expect(
    server.seen
      .filter((row) => row.path.endsWith("/runs/stream"))
      .map((row) => row.workspace),
  ).toEqual([P, T]);
});

it("discards a decoded replay after switching and refuses retained replay callbacks quietly", async () => {
  const server = fixture();
  const { view, select } = mount();
  await waitFor(() =>
    expect(view.result.current.metadata.isSuccess).toBe(true),
  );
  const retained = view.result.current.chat;
  server.delay("replay");
  let pending!: Promise<boolean>;
  act(() => {
    pending = retained.regenerateMessage("thread-1", "history");
  });
  await waitFor(() => expect(server.getRelease()).toBeDefined());
  await select();
  mocks.error.mockClear();
  mocks.start.mockClear();
  await act(async () => {
    server.getRelease()!();
    expect(await pending).toBe(false);
  });
  server.delay(null);
  const before = server.seen.length;
  await act(async () => {
    expect(await retained.regenerateMessage("thread-1", "history")).toBe(false);
    expect(
      await retained.editAndRegenerateMessage("thread-1", "history", "Stale"),
    ).toBe(false);
  });
  expect(server.seen).toHaveLength(before);
  expect(server.seen.some((row) => row.path.endsWith("/runs/stream"))).toBe(
    false,
  );
  expect(mocks.error).not.toHaveBeenCalled();
  expect(mocks.start).not.toHaveBeenCalled();
  expect(view.result.current.metadata.data?.values.title).toBe(T);
});
