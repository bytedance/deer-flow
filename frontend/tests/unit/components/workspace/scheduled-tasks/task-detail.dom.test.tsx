import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";

import { TaskDetail } from "@/components/workspace/scheduled-tasks/task-detail";
import { I18nProvider } from "@/core/i18n/context";
import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";

import { expectNoRawIdentifiers } from "../../../helpers/readable";

const { fetchRuns } = rs.hoisted(() => ({ fetchRuns: rs.fn() }));

rs.mock("@/core/scheduled-tasks/api", () => ({
  fetchScheduledTaskRuns: fetchRuns,
  pauseScheduledTask: rs.fn(),
  resumeScheduledTask: rs.fn(),
  triggerScheduledTask: rs.fn(),
  deleteScheduledTask: rs.fn(),
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ models: [], tokenUsageEnabled: true }),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
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

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  fetchRuns.mockReset();
  document.cookie = "locale=; max-age=0; path=/";
});

function task(overrides: Partial<ScheduledTask> = {}): ScheduledTask {
  return {
    id: "task-0123456789abcdef0123",
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    assistant_id: "lead_agent",
    title: "Release checklist",
    prompt: "Read release-checklist.md and list every unchecked item.",
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * 1-5" },
    timezone: "Asia/Shanghai",
    status: "enabled",
    next_run_at: "2099-10-07T01:00:00+00:00",
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    run_count: 0,
    goal_objective: null,
    max_runs: null,
    end_at: null,
    origin_thread_id: null,
    standing_notes: [],
    stop_condition: null,
    automatic_runs_used: 0,
    active_run_status: null,
    created_at: "2026-10-05T00:00:00+00:00",
    updated_at: "2026-10-05T00:00:00+00:00",
    ...overrides,
  };
}

function run(overrides: Partial<ScheduledTaskRun> = {}): ScheduledTaskRun {
  return {
    id: "task-run-0123456789abcdef01",
    task_id: "task-0123456789abcdef0123",
    thread_id: "83d5133d-f8aa-4095-9bba-2aca03f8f61c",
    run_id: "41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
    scheduled_for: "2026-10-05T12:21:53+00:00",
    trigger: "scheduled",
    status: "success",
    error: null,
    attempt_count: 1,
    started_at: null,
    finished_at: "2026-10-05T12:22:04+00:00",
    created_at: "2026-10-05T12:21:53+00:00",
    run_number: 2,
    total_tokens: 43651,
    summary: "Every item is already checked.",
    ...overrides,
  };
}

function renderDetail(
  value: ScheduledTask,
  {
    runs = [],
    locale = "en-US",
    toolEnabled = true,
    createBlocked = false,
  }: {
    runs?: ScheduledTaskRun[];
    locale?: "en-US" | "zh-CN";
    toolEnabled?: boolean;
    createBlocked?: boolean;
  } = {},
) {
  document.cookie = `locale=${locale}; path=/`;
  fetchRuns.mockResolvedValue(runs);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <TaskDetail
          task={value}
          toolEnabled={toolEnabled}
          createBlocked={createBlocked}
          onEdit={rs.fn()}
          onDuplicate={rs.fn()}
        />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("TaskDetail", () => {
  test("an active task shows Runs, Stops when, goal, Does, notes and history without raw identifiers", async () => {
    const view = renderDetail(
      task({
        stop_condition: "every item on the checklist is checked",
        goal_objective: "status.md lists every unchecked item",
        max_runs: 60,
        automatic_runs_used: 2,
        standing_notes: ["Skip the docs section"],
        origin_thread_id: "c04264b7-891e-451a-92af-8c084e1eed55",
        run_count: 2,
        last_run_at: "2026-10-05T12:21:53+00:00",
      }),
      { runs: [run()] },
    );
    await screen.findByTestId("scheduled-run-row");
    const detail = screen.getByTestId("scheduled-task-detail");
    for (const label of [
      "Runs",
      "Stops when",
      "Each run's goal",
      "Does",
      "Notes from chat",
      "History",
    ]) {
      expect(within(detail).getByText(label)).toBeTruthy();
    }
    expect(detail.textContent).toContain("Weekdays at 09:00 (Asia/Shanghai)");
    expect(screen.getByTestId("scheduled-task-stops-when").textContent).toBe(
      "every item on the checklist is checked, pauses itself",
    );
    for (const line of [
      "Safety cap: 2 of 60 runs used",
      "Trial runs don't count.",
      "Pauses after 3 runs in a row miss the goal",
    ]) {
      expect(within(detail).getByText(line)).toBeTruthy();
    }
    expect(screen.getByTestId("scheduled-task-status").textContent).toBe(
      "Active",
    );
    expect(screen.getByTestId("scheduled-task-notes").textContent).toBe(
      "Skip the docs section",
    );
    const row = screen.getByTestId("scheduled-run-row");
    expect(row.getAttribute("data-run-id")).toBe(
      "41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
    );
    expect(row.textContent).toContain("Run 2");
    expect(row.textContent).toContain("43.7K tokens");
    expect(
      within(row)
        .getByRole("link", { name: /Open chat/ })
        .getAttribute("href"),
    ).toBe("/workspace/chats/83d5133d-f8aa-4095-9bba-2aca03f8f61c");
    expect(
      screen.getByTestId("scheduled-task-origin-link").getAttribute("href"),
    ).toBe("/workspace/chats/c04264b7-891e-451a-92af-8c084e1eed55");
    expect(within(detail).getByRole("button", { name: /Pause/ })).toBeTruthy();
    expect(within(detail).queryByRole("button", { name: /Resume/ })).toBeNull();
    expectNoRawIdentifiers(view.container);
  });

  test("a task paused by its agent explains it and links to that run", async () => {
    renderDetail(
      task({
        status: "paused",
        stop_condition: "every item is checked",
        last_error:
          "stopped by the agent in run 41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
      }),
      {
        runs: [
          run({
            stop_requested_run_id: "41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
          }),
        ],
      },
    );
    const notice = await screen.findByTestId("scheduled-task-outcome");
    expect(notice.getAttribute("data-outcome")).toBe("pausedByAgent");
    await screen.findByRole("link", { name: "See that run" });
    expect(
      screen.getByRole("link", { name: "See that run" }).getAttribute("href"),
    ).toBe("/workspace/chats/83d5133d-f8aa-4095-9bba-2aca03f8f61c");
    expect(screen.getByTestId("scheduled-task-status").textContent).toBe(
      "Paused by agent",
    );
    expect(screen.getByTestId("scheduled-task-stops-when").textContent).toMatch(
      /^every item is checked, pauses itself✓ Reached /,
    );
    expect(screen.getByTestId("scheduled-task-next").textContent).toContain(
      "Not running while paused",
    );
  });

  test("a recurring task mid-run reads Running now and blocks changes", async () => {
    renderDetail(task({ status: "enabled", active_run_status: "running" }));
    await screen.findByText("No runs yet");
    expect(screen.getByTestId("scheduled-task-status").textContent).toBe(
      "Running now",
    );
    expect(screen.getByTestId("scheduled-task-next").textContent).toBe(
      "Running now",
    );
    for (const name of ["Pause", "Run once now", "Edit"]) {
      expect(screen.getByRole("button", { name })).toHaveProperty(
        "disabled",
        true,
      );
    }
  });

  test("a task finished by its run limit offers Extend limit and no Pause", async () => {
    renderDetail(
      task({
        status: "completed",
        next_run_at: null,
        max_runs: 5,
        automatic_runs_used: 5,
      }),
    );
    const notice = await screen.findByTestId("scheduled-task-outcome");
    expect(notice.textContent).toContain("Finished: all 5 runs used");
    expect(
      within(notice).getByRole("button", { name: "Extend limit" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByTestId("scheduled-task-next").textContent).toBe(
      "Finished — no more runs",
    );
  });

  test("without the chat tool the stop condition is hidden; caps still show", async () => {
    renderDetail(
      task({
        stop_condition: "the list is empty",
        end_at: "2099-12-31T10:00:00Z",
      }),
      { toolEnabled: false },
    );
    await screen.findByText("No runs yet");
    const stops = screen.getByTestId("scheduled-task-stops-when").textContent;
    expect(stops).not.toContain("the list is empty");
    expect(stops).toMatch(/^At /);
  });

  test("Chinese detail uses the glossary and shows no raw identifiers", async () => {
    const view = renderDetail(
      task({
        title: "发布清单未完成项监控",
        prompt: "读取清单并列出未勾选的项。",
        stop_condition: "清单上的所有项都已勾选",
        max_runs: 5,
        automatic_runs_used: 2,
        context_mode: "reuse_thread",
        thread_id: "f71edb2f-7fbe-45e3-84cf-a3f47c5c0635",
        schedule_type: "interval",
        schedule_spec: { every_seconds: 60 },
        timezone: "UTC",
      }),
      {
        locale: "zh-CN",
        runs: [
          run({ trigger: "manual", run_number: null, summary: null }),
          run({
            id: "task-run-failedfailedfailed01",
            status: "failed",
            error: "boom",
            summary: null,
          }),
        ],
      },
    );
    await screen.findAllByTestId("scheduled-run-row");
    const detail = screen.getByTestId("scheduled-task-detail");
    for (const label of ["运行时间", "何时停止", "执行内容", "运行记录"]) {
      expect(within(detail).getByText(label)).toBeTruthy();
    }
    expect(detail.textContent).toContain("每 1 分钟");
    expect(detail.textContent).toContain(
      "清单上的所有项都已勾选，满足后自动暂停",
    );
    expect(detail.textContent).toContain("保险上限：已用 2/5 次");
    expect(detail.textContent).toContain("在已有对话中运行");
    expect(detail.textContent).toContain("试运行");
    expect(detail.textContent).toContain("运行中出错");
    // The raw error sits only inside the closed "Details" disclosure.
    const details = within(detail).getByText("详细信息").closest("details");
    expect(details?.open).toBe(false);
    const visible = Array.from(detail.querySelectorAll("details")).reduce(
      (text, node) => text.replace(node.textContent ?? "", ""),
      view.container.textContent ?? "",
    );
    expect(visible).not.toContain("boom");
    expectNoRawIdentifiers(visible);
  });
});
