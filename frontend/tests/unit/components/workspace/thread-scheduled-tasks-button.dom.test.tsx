import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { ThreadScheduledTasksButton } from "@/components/workspace/thread-scheduled-tasks-button";
import { GatewayApiError } from "@/core/api/errors";
import { I18nProvider } from "@/core/i18n/context";
import type { ThreadScheduledTask } from "@/core/scheduled-tasks/types";

const api = rs.hoisted(() => ({ fetchThreadScheduledTasks: rs.fn() }));
const feature = rs.hoisted(() => ({ available: true }));

rs.mock("@/core/scheduled-tasks/api", () => ({
  ...api,
  createScheduledTask: rs.fn(),
  deleteScheduledTask: rs.fn(),
  fetchScheduledTask: rs.fn(),
  fetchScheduledTasks: rs.fn(),
  pauseScheduledTask: rs.fn(),
  resumeScheduledTask: rs.fn(),
  triggerScheduledTask: rs.fn(),
  updateScheduledTask: rs.fn(),
}));
rs.mock("@/core/features", () => ({
  useScheduledTasksFeature: () => ({
    available: feature.available,
    running: true,
    toolEnabled: true,
    minIntervalSeconds: 60,
    isLoading: false,
  }),
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

const THREAD = "c04264b7-891e-451a-92af-8c084e1eed55";
const clients: QueryClient[] = [];

beforeEach(() => {
  feature.available = true;
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  api.fetchThreadScheduledTasks.mockReset();
  document.cookie = "locale=; max-age=0; path=/";
});

function row(
  id: string,
  relation: ThreadScheduledTask["thread_relation"],
): ThreadScheduledTask {
  return {
    id,
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    assistant_id: null,
    title: id,
    prompt: "",
    schedule_type: "interval",
    schedule_spec: { every_seconds: 3600 },
    timezone: "UTC",
    status: "enabled",
    next_run_at: null,
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    run_count: 0,
    created_at: "",
    updated_at: "",
    thread_relation: relation,
    thread_run:
      relation === "run"
        ? {
            run_number: 2,
            trigger: "scheduled",
            scheduled_for: "2026-10-05T12:21:53+00:00",
            status: "success",
          }
        : null,
  };
}

function renderButton(locale: "en-US" | "zh-CN" = "en-US") {
  document.cookie = `locale=${locale}; path=/`;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <ThreadScheduledTasksButton threadId={THREAD} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const button = () => screen.queryByTestId("thread-scheduled-tasks-button");

describe("ThreadScheduledTasksButton", () => {
  test("is hidden for a chat without tasks", async () => {
    api.fetchThreadScheduledTasks.mockResolvedValue([]);
    renderButton();
    await waitFor(() =>
      expect(api.fetchThreadScheduledTasks).toHaveBeenCalledWith(THREAD),
    );
    expect(button()).toBeNull();
  });

  test("is hidden when the list fails to load", async () => {
    api.fetchThreadScheduledTasks.mockRejectedValue(
      new GatewayApiError({
        message: "boom",
        status: 500,
        code: null,
        params: {},
        rawMessage: "boom",
      }),
    );
    renderButton();
    await waitFor(() =>
      expect(api.fetchThreadScheduledTasks).toHaveBeenCalled(),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(button()).toBeNull();
  });

  test("is hidden and does not fetch when the feature is unavailable", async () => {
    feature.available = false;
    renderButton();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(button()).toBeNull();
    expect(api.fetchThreadScheduledTasks).not.toHaveBeenCalled();
  });

  test("one task links straight to it with a count of 1", async () => {
    api.fetchThreadScheduledTasks.mockResolvedValue([row("task-a", "origin")]);
    renderButton();
    await waitFor(() => expect(button()).not.toBeNull());
    expect(button()?.getAttribute("href")).toBe(
      "/workspace/scheduled-tasks?task_id=task-a",
    );
    expect(button()?.getAttribute("aria-label")).toBe(
      "1 scheduled task in this chat",
    );
    expect(button()?.textContent).toContain("1");
  });

  test("several tasks link to the list filtered to this chat", async () => {
    api.fetchThreadScheduledTasks.mockResolvedValue([
      row("task-a", "origin"),
      row("task-b", "reuse"),
      row("task-c", "origin"),
    ]);
    renderButton("zh-CN");
    await waitFor(() => expect(button()).not.toBeNull());
    expect(button()?.getAttribute("href")).toBe(
      `/workspace/scheduled-tasks?thread_id=${THREAD}`,
    );
    expect(button()?.getAttribute("aria-label")).toBe("本对话有 3 个定时任务");
    expect(button()?.textContent).toContain("3");
  });

  test("a run conversation links to its task", async () => {
    api.fetchThreadScheduledTasks.mockResolvedValue([row("task-a", "run")]);
    renderButton();
    await waitFor(() => expect(button()).not.toBeNull());
    expect(button()?.getAttribute("href")).toBe(
      "/workspace/scheduled-tasks?task_id=task-a",
    );
    expect(button()?.textContent).toBe("Scheduled task");
  });
});
