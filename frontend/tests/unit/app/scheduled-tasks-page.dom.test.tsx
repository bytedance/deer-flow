import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { PropsWithChildren, ReactNode } from "react";

const mocks = rs.hoisted(() => ({
  search: "",
  replace: rs.fn(),
  fetchTasks: rs.fn(),
  fetchThreadTasks: rs.fn(),
  feature: {
    available: true,
    running: true,
    toolEnabled: true,
    minIntervalSeconds: 60,
    isLoading: false,
  },
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/scheduled-tasks",
  useRouter: () => ({ push: rs.fn(), replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));
rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: PropsWithChildren) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => <div />,
  WorkspaceBody: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));
rs.mock("@/core/features/hooks", () => ({
  useScheduledTasksFeature: () => mocks.feature,
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ models: [], tokenUsageEnabled: false }),
}));
rs.mock("@/core/scheduled-tasks/api", () => ({
  fetchScheduledTasks: mocks.fetchTasks,
  fetchThreadScheduledTasks: mocks.fetchThreadTasks,
  fetchScheduledTaskRuns: async () => [],
  pauseScheduledTask: rs.fn(),
  resumeScheduledTask: rs.fn(),
  triggerScheduledTask: rs.fn(),
  deleteScheduledTask: rs.fn(),
  createScheduledTask: rs.fn(),
  updateScheduledTask: rs.fn(),
}));

import ScheduledTasksPage from "@/app/workspace/scheduled-tasks/page";
import { GatewayApiError } from "@/core/api/errors";
import { I18nProvider } from "@/core/i18n/context";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

function task(overrides: Partial<ScheduledTask>): ScheduledTask {
  return {
    id: "task-a",
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    assistant_id: null,
    title: "Alpha report",
    prompt: "Write the alpha report.",
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
    status: "enabled",
    next_run_at: "2099-01-01T09:00:00Z",
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    run_count: 0,
    automatic_runs_used: 0,
    active_run_status: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

const ALPHA = task({});
const BETA = task({ id: "task-b", title: "Beta digest" });

const clients: QueryClient[] = [];

function renderPage(locale: "en-US" | "zh-CN" = "en-US") {
  document.cookie = `locale=${locale}; path=/`;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <ScheduledTasksPage />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return client;
}

const detail = () => screen.getByTestId("scheduled-task-detail");

beforeEach(() => {
  mocks.search = "";
  mocks.feature = {
    available: true,
    running: true,
    toolEnabled: true,
    minIntervalSeconds: 60,
    isLoading: false,
  };
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  mocks.replace.mockReset();
  mocks.fetchTasks.mockReset();
  mocks.fetchThreadTasks.mockReset();
  document.cookie = "locale=; max-age=0; path=/";
});

describe("ScheduledTasksPage", () => {
  it("keeps showing the task the user paused after it leaves the Active tab", async () => {
    mocks.fetchTasks.mockResolvedValue([ALPHA, BETA]);
    const client = renderPage();
    fireEvent.click(await screen.findByRole("radio", { name: "Active, 2" }));
    await waitFor(() => expect(detail().textContent).toContain("Alpha report"));
    // Pausing it moves it to the Paused tab on the next list refresh.
    mocks.fetchTasks.mockResolvedValue([task({ status: "paused" }), BETA]);
    await client.invalidateQueries({ queryKey: ["scheduled-tasks"] });
    await screen.findByRole("radio", { name: "Paused, 1" });
    expect(detail().textContent).toContain("Alpha report");
    expect(
      within(detail()).getByTestId("scheduled-task-status").textContent,
    ).toBe("Paused");
  });

  it("a deep link selects its task even when it is not the first one", async () => {
    mocks.search = "task_id=task-b";
    mocks.fetchTasks.mockResolvedValue([ALPHA, BETA]);
    renderPage();
    await waitFor(() => expect(detail().textContent).toContain("Beta digest"));
  });

  it("a deep link to a deleted task says so instead of showing another task", async () => {
    mocks.search = "task_id=task-gone";
    mocks.fetchTasks.mockResolvedValue([ALPHA, BETA]);
    renderPage();
    const missing = await screen.findByTestId("scheduled-task-link-missing");
    expect(missing.textContent).toContain("This task no longer exists.");
    expect(screen.queryByTestId("scheduled-task-detail")).toBeNull();
  });

  it("a chat filter lists the chat's own tasks and explains a task outside it", async () => {
    mocks.search = "thread_id=chat-1&task_id=task-b";
    mocks.fetchThreadTasks.mockResolvedValue([
      { ...ALPHA, thread_relation: "origin" },
      { ...BETA, thread_relation: "run" },
    ]);
    renderPage();
    const missing = await screen.findByTestId("scheduled-task-link-missing");
    expect(missing.textContent).toContain(
      "This task isn't one of this chat's tasks.",
    );
    expect(screen.getByRole("radio", { name: "All, 1" })).toBeTruthy();
    fireEvent.click(within(missing).getByRole("button", { name: "Show all" }));
    expect(mocks.replace).toHaveBeenCalledWith(
      "/workspace/scheduled-tasks?task_id=task-b",
      { scroll: false },
    );
  });

  it("says it is loading instead of showing empty tabs", async () => {
    mocks.fetchTasks.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(
      (await screen.findByTestId("scheduled-task-list-loading")).textContent,
    ).toBe("Loading tasks…");
  });

  it("holds the chat wording while features load", async () => {
    mocks.feature = { ...mocks.feature, toolEnabled: false, isLoading: true };
    mocks.fetchTasks.mockResolvedValue([]);
    renderPage();
    expect(
      await screen.findByText(
        "Tasks DeerFlow runs for you on a schedule. You can also just ask in any chat.",
      ),
    ).toBeTruthy();
  });

  it("a load error reads in the locale's punctuation, with the server text behind Details", async () => {
    mocks.fetchTasks.mockRejectedValue(
      new GatewayApiError({
        message: "database is locked",
        status: 500,
        code: null,
        params: {},
        rawMessage: "database is locked",
      }),
    );
    renderPage("zh-CN");
    const error = await screen.findByTestId("scheduled-task-load-error");
    expect(within(error).getByRole("alert").textContent).toBe(
      "加载定时任务失败：出了点问题。",
    );
    const details = within(error).getByText("详细信息").closest("details");
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain("database is locked");
  });
});
