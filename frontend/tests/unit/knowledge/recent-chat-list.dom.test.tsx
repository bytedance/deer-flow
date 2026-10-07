/**
 * KB-isolation contract for the global RecentChatList (spec §5.2): threads
 * carrying ``metadata.kb_id`` belong to the knowledge page and must never
 * leak into the global sidebar list.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

rs.mock("next/navigation", () => ({
  useParams: () => ({}),
  usePathname: () => "/workspace/chats",
  useRouter: () => ({ push: () => undefined, replace: () => undefined }),
}));

rs.mock("@/core/features", () => ({
  useKnowledgeBaseEnabled: () => ({ enabled: true, scopeSelectionEnabled: false, isLoading: false }),
}));

// 基座版组件带项目分组查询；本对只钉 kb 隔离，项目面给空桩（与分组模式无关）。
rs.mock("@/core/projects", () => ({
  useProjects: () => ({ data: [], isError: false, isLoading: false }),
  useCreateProject: () => ({ mutate: rs.fn(), isPending: false }),
  useMoveThreadToProject: () => ({ mutate: rs.fn() }),
}));

rs.mock("@/core/settings", () => ({
  useLocalSettings: () => [{ projectsDisplayMode: "flat" }, rs.fn()],
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "u1", system_role: "user" } }),
}));

// 基座版行组件挂两个本地 provider 钩子；本对只钉 kb 隔离，给最小桩。
rs.mock("@/components/workspace/thread-delete-dialog", () => ({
  useThreadDeleteDialog: () => rs.fn(),
}));

rs.mock("@/components/workspace/use-thread-archive-action", () => ({
  useThreadArchiveAction: () => ({ isPending: false, setArchived: rs.fn() }),
}));

rs.mock("@/core/threads/hooks", () => ({
  useInfiniteThreads: rs.fn(),
  useDeleteThread: () => ({ mutate: rs.fn() }),
  useRenameThread: () => ({ mutate: rs.fn() }),
  usePinThread: () => ({ mutate: rs.fn() }),
  useMoveThreadToProject: () => ({ mutate: rs.fn() }),
}));

rs.mock("@/components/workspace/thread-list-virtualizer", () => ({
  VirtualThreadList: ({
    items,
    renderItem,
  }: {
    items: Array<Record<string, unknown>>;
    renderItem: (item: Record<string, unknown>) => React.ReactNode;
  }) => <div data-testid="virtual-list">{items.map((item) => renderItem(item))}</div>,
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

import { SidebarProvider } from "@/components/ui/sidebar";
import { RecentChatList } from "@/components/workspace/recent-chat-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { useInfiniteThreads } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

const mockedUseInfiniteThreads = rs.mocked(useInfiniteThreads);

function thread(id: string, title: string, metadata: Record<string, unknown>): AgentThread {
  return {
    thread_id: id,
    created_at: "2026-08-09T10:00:00Z",
    updated_at: "2026-08-09T10:00:00Z",
    metadata,
    status: "idle",
    values: { title },
  } as unknown as AgentThread;
}

function mockThreads(threads: AgentThread[]) {
  mockedUseInfiniteThreads.mockReturnValue({
    data: { pages: [threads], pageParams: [0] },
    fetchNextPage: rs.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  } as never);
}

function renderList() {
  return render(
    <I18nContext.Provider value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}>
      <SidebarProvider>
        <RecentChatList />
      </SidebarProvider>
    </I18nContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("RecentChatList kb isolation", () => {
  it("hides threads carrying metadata.kb_id from the global list", () => {
    mockThreads([
      thread("t-plain", "General chat", { agent_name: "researcher" }),
      thread("t-kb", "KB conversation", { agent_name: "rag", kb_id: "kb-1" }),
    ]);

    renderList();

    expect(screen.getByText("General chat")).toBeTruthy();
    expect(screen.queryByText("KB conversation")).toBeNull();
  });

  it("renders nothing when every loaded thread is kb-bound", () => {
    mockThreads([thread("t-kb", "KB conversation", { kb_id: "kb-1" })]);

    renderList();

    // RecentChatList itself returns null — no sidebar group, no thread links.
    expect(screen.queryByText("KB conversation")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
