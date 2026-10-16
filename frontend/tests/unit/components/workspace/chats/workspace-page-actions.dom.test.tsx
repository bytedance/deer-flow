import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import ChatPage from "@/components/workspace/chats/chat-page";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

const mocks = rs.hoisted(() => ({
  isNew: true,
  prepare: null as (() => Promise<void>) | null,
  referenceAttached: null as (() => void) | null,
  branchTurn: null as ((id: string, ids: string[]) => Promise<void>) | null,
  branch: rs.fn(),
  push: rs.fn(),
  replace: rs.fn(),
  success: rs.fn(),
  error: rs.fn(),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams("project=project"),
  usePathname: () => "/workspace/chats/new",
}));
rs.mock("sonner", () => ({
  toast: { success: mocks.success, error: mocks.error },
}));
rs.mock("@/components/workspace/chats/use-thread-chat", () => ({
  useThreadChat: () => ({
    threadId: "thread-1",
    isNewThread: mocks.isNew,
    isMock: false,
    setThreadId: rs.fn(),
    setIsNewThread: rs.fn(),
  }),
}));
rs.mock("@/components/workspace/chats/use-chat-mode", () => ({
  useSpecificChatMode: () => undefined,
}));
rs.mock("@/components/workspace/chats/use-mark-open-thread-read", () => ({
  useMarkOpenThreadRead: () => rs.fn(),
}));
rs.mock("@/core/features", () => ({
  useBrowserControlEnabled: () => ({ enabled: false }),
  useKnowledgeBaseEnabled: () => ({ scopeSelectionEnabled: false }),
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ tokenUsageEnabled: false }),
}));
rs.mock("@/core/notification/hooks", () => ({
  useNotification: () => ({ showNotification: rs.fn() }),
}));
rs.mock("@/core/projects", () => ({ useProject: () => ({ data: null }) }));
rs.mock("@/core/scheduled-tasks/events", () => ({
  useThreadScheduledTaskEvents: () => ({ data: [] }),
}));
rs.mock("@/core/scheduled-tasks/hooks", () => ({
  useScheduleToolResultRefresh: () => undefined,
}));
rs.mock("@/core/settings", () => ({
  useThreadSettings: () => [DEFAULT_LOCAL_SETTINGS, rs.fn()],
  useLocalSettings: () => [DEFAULT_LOCAL_SETTINGS, rs.fn()],
}));
// These operations were verified with real SDK/REST in #35/#39. This fixture
// isolates the actual page's after-await side effects; createThread stays real.
rs.mock("@/core/threads/hooks", () => ({
  INFINITE_THREADS_QUERY_KEY_PREFIX: ["threads", "searchInfinite"],
  useBranchThread: () => ({ mutateAsync: mocks.branch, isPending: false }),
  useThreadMetadata: () => ({
    data: { values: {}, metadata: {} },
    isLoading: false,
    isFetching: false,
  }),
  useThreadTokenUsage: () => ({ data: undefined }),
  useThreadStream: () => ({
    thread: { messages: [], values: { todos: [] }, isLoading: false },
    pendingUsageMessages: [],
    sendMessage: rs.fn(),
    regenerateMessage: rs.fn(),
    editAndRegenerateMessage: rs.fn(),
    isUploading: false,
    isHistoryLoading: false,
    hasMoreHistory: false,
    loadMoreHistory: rs.fn(),
  }),
}));
rs.mock("@/components/workspace/input-box", () => ({
  InputBox: ({
    onPrepareThread,
    onReferenceFileAttached,
  }: {
    onPrepareThread: () => Promise<void>;
    onReferenceFileAttached: () => void;
  }) => {
    mocks.prepare = onPrepareThread;
    mocks.referenceAttached = onReferenceFileAttached;
    return null;
  },
}));
rs.mock("@/components/workspace/messages", () => ({
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM: 0,
  MessageList: ({
    onBranchTurn,
  }: {
    onBranchTurn: (id: string, ids: string[]) => Promise<void>;
  }) => {
    mocks.branchTurn = onBranchTurn;
    return null;
  },
}));
rs.mock("@/components/workspace/chats/chat-box", () => ({
  ChatBox: ({ children }: { children: ReactNode }) => children,
}));
rs.mock("@/components/workspace/sidecar", () => ({
  SidecarProvider: ({ children }: { children: ReactNode }) => children,
  SidecarTrigger: () => null,
}));
rs.mock("@/components/ui/sidebar", () => ({ SidebarTrigger: () => null }));
rs.mock("@/components/workspace/artifacts", () => ({
  ArtifactTrigger: () => null,
}));
rs.mock("@/components/workspace/browser-view", () => ({
  BrowserTrigger: () => null,
}));
rs.mock("@/components/workspace/context-usage-badge", () => ({
  ContextUsageBadge: () => null,
}));
rs.mock("@/components/workspace/export-trigger", () => ({
  ExportTrigger: () => null,
}));
rs.mock("@/components/workspace/goal-status", () => ({
  GoalStatus: () => null,
}));
rs.mock("@/components/workspace/knowledge-scope-selector", () => ({
  KnowledgeScopeSelector: () => null,
}));
rs.mock("@/components/workspace/thread-archive-status", () => ({
  ThreadArchiveStatus: () => null,
}));
rs.mock("@/components/workspace/thread-background-tasks", () => ({
  ThreadBackgroundTasks: () => null,
}));
rs.mock("@/components/workspace/thread-extension-actions", () => ({
  ThreadExtensionActions: () => null,
}));
rs.mock("@/components/workspace/thread-scheduled-tasks-button", () => ({
  ThreadScheduledTasksButton: () => null,
}));
rs.mock("@/components/workspace/thread-subagent-batches", () => ({
  ThreadSubagentBatches: () => null,
}));
rs.mock("@/components/workspace/thread-title", () => ({
  ThreadTitle: () => null,
}));
rs.mock("@/components/workspace/todo-list", () => ({ TodoList: () => null }));
rs.mock("@/components/workspace/token-usage-indicator", () => ({
  TokenUsageIndicator: () => null,
}));
rs.mock("@/components/workspace/welcome", () => ({ Welcome: () => null }));

const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
function fixture() {
  const seen: { workspace: string | null; body: unknown }[] = [];
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
      if (path === "/api/threads") {
        seen.push({
          workspace,
          body:
            typeof init?.body === "string"
              ? (JSON.parse(init.body) as unknown)
              : null,
        });
        const body = {
          thread_id: "thread-1",
          metadata: { deerflow_project_id: "project", marker: workspace },
        };
        const response = Response.json(body);
        if (hold)
          response.json = () =>
            new Promise((resolve) => {
              release = () => resolve(body);
            });
        return response;
      }
      throw new Error(`Unexpected page request ${path}`);
    },
  );
  return {
    seen,
    hold: () => {
      hold = true;
    },
    getRelease: () => release,
  };
}
function mount(workspace = true) {
  let control: WorkspaceContextValue | null = null;
  let cache: QueryClient | null = null;
  function Controls() {
    control = useWorkspaceContext();
    return null;
  }
  function Probe() {
    cache = useQueryClient();
    return null;
  }
  const client = new QueryClient();
  const tree = () => (
    <AuthProvider
      initialUser={{
        id: "alice",
        email: "alice@example.test",
        system_role: "user",
        needs_setup: false,
      }}
    >
      <QueryClientProvider client={client}>
        <I18nContext.Provider
          value={{ locale: "en-US", t: enUS, setLocale: () => undefined }}
        >
          <WorkspaceProvider enabled={workspace}>
            <Controls />
            <WorkspaceReadyBoundary>
              <Probe />
              <ChatPage />
            </WorkspaceReadyBoundary>
          </WorkspaceProvider>
        </I18nContext.Provider>
      </QueryClientProvider>
    </AuthProvider>
  );
  const view = render(tree());
  const ready = async () => {
    if (workspace)
      await waitFor(() => expect(control?.state.status).toBe("ready"));
    // ChatPage deliberately waits until its mount effect before rendering InputBox.
    view.rerender(tree());
    await waitFor(() => expect(mocks.prepare).not.toBeNull());
  };
  return {
    ready,
    unmount: () => {
      view.unmount();
      client.clear();
    },
    cache: () => cache!,
    select: async () => {
      mocks.prepare = null;
      await act(async () => {
        expect(await control!.select(T)).toBe(true);
      });
      await ready();
    },
  };
}
beforeEach(() => {
  mocks.isNew = true;
  mocks.prepare = null;
  mocks.branchTurn = null;
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.unstubAllGlobals();
  rs.clearAllMocks();
});

it("prepares project-born threads through each confirmed page client before publishing metadata", async () => {
  const server = fixture();
  const nativePage = mount(false);
  await nativePage.ready();
  await act(async () => {
    await mocks.prepare!();
  });
  nativePage.unmount();
  const page = mount();
  await page.ready();
  await act(async () => {
    await mocks.prepare!();
  });
  await page.select();
  await act(async () => {
    await mocks.prepare!();
  });
  expect(server.seen.map((row) => row.workspace)).toEqual([null, P, T]);
  expect(
    server.seen.every(
      (row) =>
        JSON.stringify(row.body) ===
        JSON.stringify({ thread_id: "thread-1", project_id: "project" }),
    ),
  ).toBe(true);
  expect(
    page.cache().getQueryData(["thread", "metadata", "thread-1", false]),
  ).toMatchObject({ metadata: { marker: T } });
  const historyWrite = rs
    .spyOn(history, "replaceState")
    .mockImplementation(() => undefined);
  act(() => {
    mocks.referenceAttached!();
  });
  expect(historyWrite).toHaveBeenCalledWith(
    null,
    "",
    `/workspace/chats/thread-1?workspace_id=${T}`,
  );
  expect(mocks.replace).not.toHaveBeenCalled();
});

it("refuses late prepared thread metadata and the retained page callback after switching", async () => {
  const server = fixture();
  const page = mount();
  await page.ready();
  const prepare = mocks.prepare!;
  const referenceAttached = mocks.referenceAttached!;
  const replaceState = rs
    .spyOn(history, "replaceState")
    .mockImplementation(() => undefined);
  const oldCache = page.cache();
  server.hold();
  let pending!: Promise<unknown>;
  act(() => {
    pending = prepare().catch((error: unknown) => error);
  });
  await waitFor(() => expect(server.getRelease()).toBeDefined());
  await page.select();
  await act(async () => {
    server.getRelease()!();
  });
  expect(await pending).toMatchObject({ name: "AbortError" });
  await expect(prepare()).rejects.toMatchObject({ name: "AbortError" });
  act(() => {
    referenceAttached();
  });
  expect(replaceState).not.toHaveBeenCalled();
  expect(server.seen).toHaveLength(1);
  expect(
    oldCache.getQueryData(["thread", "metadata", "thread-1", false]),
  ).toBeUndefined();
  expect(
    page.cache().getQueryData(["thread", "metadata", "thread-1", false]),
  ).toBeUndefined();
  expect(mocks.error).not.toHaveBeenCalled();
});

it("drops late branch routing and retained branch dispatch from the previous page lifetime", async () => {
  fixture();
  mocks.isNew = false;
  let release!: (value: { thread_id: string }) => void;
  mocks.branch.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const page = mount();
  await page.ready();
  const branch = mocks.branchTurn!;
  let pending!: Promise<void>;
  act(() => {
    pending = branch("message", ["message"]);
  });
  await waitFor(() => expect(mocks.branch).toHaveBeenCalledTimes(1));
  await page.select();
  await act(async () => {
    release({ thread_id: "old-branch" });
    await pending;
  });
  mocks.branch.mockResolvedValue({ thread_id: "another-old-branch" });
  await act(async () => {
    await branch("message", ["message"]);
  });
  expect(mocks.branch).toHaveBeenCalledTimes(1);
  expect(mocks.push).not.toHaveBeenCalled();
  expect(mocks.success).not.toHaveBeenCalled();
  expect(mocks.error).not.toHaveBeenCalled();
  mocks.branch.mockResolvedValue({ thread_id: "team-branch" });
  await act(async () => {
    await mocks.branchTurn!("message", ["message"]);
  });
  expect(mocks.branch).toHaveBeenCalledTimes(2);
  expect(mocks.push).toHaveBeenCalledWith(
    `/workspace/chats/team-branch?workspace_id=${T}`,
  );
  expect(mocks.success).toHaveBeenCalledTimes(1);
});
