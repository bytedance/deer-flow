import { afterEach, describe, expect, rs, test } from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  type InfiniteData,
} from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";

const nav = rs.hoisted(() => ({ activeThreadId: null as string | null }));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () =>
    nav.activeThreadId
      ? `/workspace/chats/${nav.activeThreadId}`
      : "/workspace/chats",
  useSearchParams: () => new URLSearchParams(),
  useParams: () =>
    nav.activeThreadId ? { thread_id: nav.activeThreadId } : {},
}));

import { SidebarProvider } from "@/components/ui/sidebar";
import { RecentChatList } from "@/components/workspace/recent-chat-list";
import { ThreadDeleteDialogProvider } from "@/components/workspace/thread-delete-dialog";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import type { Locale } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

import { expectNoRawIdentifiers } from "../../helpers/readable";

const RUN_THREAD = "83d5133d-f8aa-4095-9bba-2aca03f8f61c";
const FEISHU_THREAD = "4b0f3c55-0c1e-4f0a-9d7e-5f1f8f0b6e21";
const GITHUB_THREAD = "f7f4a0c2-6a43-4c55-b6a8-1bb2b8e2d3a9";
const OWN_THREAD = "c04264b7-891e-451a-92af-8c084e1eed55";

function thread(
  id: string,
  title: string,
  metadata: Record<string, unknown>,
  unread: boolean,
): AgentThread {
  return {
    thread_id: id,
    created_at: "2026-10-05T12:00:00Z",
    updated_at: "2026-10-05T12:22:04Z",
    metadata,
    status: "idle",
    values: { title },
    unread,
  } as unknown as AgentThread;
}

const THREADS: AgentThread[] = [
  thread(
    RUN_THREAD,
    "Release checklist reminder · 10-05 20:21",
    { deerflow_origin: { kind: "schedule" }, scheduled_task_id: "task-1" },
    true,
  ),
  thread(
    FEISHU_THREAD,
    "Weekly numbers",
    { channel_source: { type: "im_channel", provider: "feishu" } },
    true,
  ),
  thread(
    GITHUB_THREAD,
    "Review the docs PR",
    {
      deerflow_origin: { kind: "github", provider: "github" },
      channel_source: { type: "im_channel", provider: "github" },
    },
    false,
  ),
  thread(OWN_THREAD, "Every weekday at 9am, check the release", {}, false),
];

const clients: QueryClient[] = [];

function renderList(locale: Locale, activeThreadId: string | null = null) {
  nav.activeThreadId = activeThreadId;
  document.cookie = `locale=${locale}; path=/`;
  // Cached thread pages never go stale, so the list renders them without a
  // backend.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  clients.push(queryClient);
  queryClient.setQueryData<InfiniteData<AgentThread[]>>(
    [...INFINITE_THREADS_QUERY_KEY_PREFIX, { archived: false }],
    { pages: [THREADS], pageParams: [0] },
  );
  const user = {
    id: "user-1",
    email: "user@example.test",
    system_role: "user",
  } as User;
  return render(
    <I18nProvider initialLocale={locale}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialUser={user}>
          <SidebarProvider>
            <ThreadDeleteDialogProvider>
              <RecentChatList />
            </ThreadDeleteDialogProvider>
          </SidebarProvider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

function rowLink(threadId: string): HTMLElement {
  const link = document.querySelector<HTMLElement>(
    `a[href="/workspace/chats/${threadId}"]`,
  );
  expect(link).not.toBeNull();
  return link!;
}

afterEach(() => {
  cleanup();
  nav.activeThreadId = null;
  document.cookie = "locale=; max-age=0; path=/";
  clients.splice(0).forEach((client) => client.clear());
});

describe("RecentChatList origin markers and unread state", () => {
  test("an unread scheduled run shows the clock, its title and the dot", async () => {
    renderList("en-US");
    const link = await screen.findByRole("link", {
      name: "Release checklist reminder · 10-05 20:21, unread",
    });
    expect(link.getAttribute("data-unread")).toBe("true");
    expect(
      within(link).getByRole("img", { name: "Scheduled run" }),
    ).not.toBeNull();
    const dot = within(link).getByTestId("thread-unread-dot");
    expect(dot.textContent).toBe("Unread");
    expect(dot.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  test("an IM thread shows its provider icon, chip and dot; a read thread has no dot", async () => {
    renderList("en-US");
    const feishu = await screen.findByRole("link", {
      name: "Weekly numbers, unread",
    });
    expect(
      within(feishu).getByRole("img", { name: "From Feishu" }),
    ).not.toBeNull();
    // The provider chip: localized name, "From …" tooltip.
    expect(
      within(feishu).getByText("Feishu").parentElement?.getAttribute("title"),
    ).toBe("From Feishu");
    expect(within(feishu).queryByTestId("thread-unread-dot")).not.toBeNull();

    const github = rowLink(GITHUB_THREAD);
    expect(
      within(github).getByRole("img", { name: "From GitHub" }),
    ).not.toBeNull();
    expect(within(github).queryByTestId("thread-unread-dot")).toBeNull();
    expect(github.getAttribute("aria-label")).toBeNull();

    const own = rowLink(OWN_THREAD);
    expect(within(own).queryByTestId("thread-origin-icon")).toBeNull();
    expect(within(own).queryByTestId("thread-unread-dot")).toBeNull();
  });

  test("the open thread never shows the dot, even while it is unread", async () => {
    renderList("en-US", RUN_THREAD);
    await screen.findByRole("link", { name: "Weekly numbers, unread" });
    const active = rowLink(RUN_THREAD);
    expect(active.getAttribute("data-active")).toBe("true");
    expect(within(active).queryByTestId("thread-unread-dot")).toBeNull();
    expect(active.getAttribute("aria-label")).toBeNull();
    expect(active.getAttribute("data-unread")).toBeNull();
    // The marker stays: it says who created the thread, not whether it is read.
    expect(
      within(active).getByRole("img", { name: "Scheduled run" }),
    ).not.toBeNull();
  });

  test("zh-CN labels read naturally", async () => {
    renderList("zh-CN");
    const run = await screen.findByRole("link", {
      name: "Release checklist reminder · 10-05 20:21，未读",
    });
    expect(within(run).getByRole("img", { name: "定时运行" })).not.toBeNull();
    expect(within(run).getByTestId("thread-unread-dot").textContent).toBe(
      "未读",
    );
    const feishu = screen.getByRole("link", { name: "Weekly numbers，未读" });
    expect(
      within(feishu).getByRole("img", { name: "来自飞书" }),
    ).not.toBeNull();
    expect(
      within(feishu).getByText("飞书").parentElement?.getAttribute("title"),
    ).toBe("来自飞书");
    expect(
      within(rowLink(GITHUB_THREAD)).getByRole("img", { name: "来自 GitHub" }),
    ).not.toBeNull();
  });

  test("the list shows no raw identifiers", async () => {
    const { container } = renderList("en-US");
    await screen.findByRole("link", { name: "Weekly numbers, unread" });
    expectNoRawIdentifiers(container);
    expect(container.textContent).not.toContain("feishu");
    expect(container.textContent).not.toContain("channel");
  });
});
