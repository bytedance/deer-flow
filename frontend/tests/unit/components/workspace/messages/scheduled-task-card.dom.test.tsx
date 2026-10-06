import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { ScheduledTaskCard } from "@/components/workspace/messages/scheduled-task-card";
import { GatewayApiError } from "@/core/api/errors";
import { I18nProvider } from "@/core/i18n/context";
import type { ScheduleToolResult } from "@/core/scheduled-tasks/tool-result";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

import { expectNoRawIdentifiers } from "../../../helpers/readable";

const api = rs.hoisted(() => ({
  fetchScheduledTask: rs.fn(),
  triggerScheduledTask: rs.fn(),
  pauseScheduledTask: rs.fn(),
  resumeScheduledTask: rs.fn(),
}));
const feature = rs.hoisted(() => ({
  value: {
    available: true,
    running: true,
    toolEnabled: true,
    minIntervalSeconds: 60,
    isLoading: false,
  },
}));

rs.mock("@/core/scheduled-tasks/api", () => ({
  ...api,
  createScheduledTask: rs.fn(),
  deleteScheduledTask: rs.fn(),
  fetchScheduledTasks: rs.fn(),
  fetchScheduledTaskRuns: rs.fn(),
  fetchThreadScheduledTasks: rs.fn(),
  updateScheduledTask: rs.fn(),
}));
rs.mock("@/core/features", () => ({
  useScheduledTasksFeature: () => feature.value,
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ models: [], tokenUsageEnabled: false }),
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

/** Every observed element reports `visible`; `emit` changes it later. */
class IntersectionObserverMock {
  static instances: IntersectionObserverMock[] = [];
  static visible = true;
  constructor(private callback: IntersectionObserverCallback) {
    IntersectionObserverMock.instances.push(this);
  }
  observe = () => {
    this.emit(IntersectionObserverMock.visible);
  };
  disconnect = () => undefined;
  unobserve = () => undefined;
  emit(isIntersecting: boolean) {
    this.callback(
      [{ isIntersecting } as IntersectionObserverEntry],
      this as never,
    );
  }
}

const TASK_ID = "task-2b559ac2af344c3f9e55b90391f7fb1a";
const THREAD_ID = "c9f49685-716d-47c9-b1dc-16518bc271e6";

function liveTask(overrides: Partial<ScheduledTask> = {}): ScheduledTask {
  return {
    id: TASK_ID,
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    assistant_id: "lead_agent",
    title: "Release checklist reminder",
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
    max_runs: 60,
    end_at: null,
    origin_thread_id: "c04264b7-891e-451a-92af-8c084e1eed55",
    standing_notes: [],
    stop_condition: "every item is checked",
    automatic_runs_used: 0,
    active_run_status: null,
    created_at: "2026-10-05T00:00:00+00:00",
    updated_at: "2026-10-05T00:00:00+00:00",
    ...overrides,
  };
}

function toolResult(
  overrides: Partial<ScheduleToolResult> = {},
): ScheduleToolResult {
  return {
    action: "create",
    display: "card",
    task: {
      id: TASK_ID,
      title: "Release checklist reminder",
      status: "enabled",
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * 1-5" },
      timezone: "Asia/Shanghai",
      next_run_local: "2099-10-07 09:00 (Asia/Shanghai)",
      active_run_status: null,
      prompt: "Read release-checklist.md and list every unchecked item.",
      stop_condition: "every item is checked",
      goal_objective: null,
      max_runs: 60,
      end_at_local: null,
      automatic_runs_used: 0,
      context_mode: "fresh_thread_per_run",
      standing_notes: [],
    },
    ...overrides,
  };
}

const clients: QueryClient[] = [];

beforeEach(() => {
  IntersectionObserverMock.visible = true;
  IntersectionObserverMock.instances = [];
  rs.stubGlobal("IntersectionObserver", IntersectionObserverMock);
  feature.value = {
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
  Object.values(api).forEach((fn) => fn.mockReset());
  rs.unstubAllGlobals();
  rs.useRealTimers();
  document.cookie = "locale=; max-age=0; path=/";
});

function renderCard(
  result: ScheduleToolResult = toolResult(),
  locale: "en-US" | "zh-CN" = "en-US",
) {
  document.cookie = `locale=${locale}; path=/`;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <ScheduledTaskCard result={result} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const card = () => screen.getByTestId("scheduled-task-card");
const button = (name: RegExp) => screen.getByRole("button", { name });

describe("ScheduledTaskCard", () => {
  test("renders the schedule, stop rule and safety cap without raw identifiers", async () => {
    api.fetchScheduledTask.mockResolvedValue(liveTask());
    renderCard();

    expect(card()?.getAttribute("aria-label")).toBe(
      "Scheduled task Release checklist reminder",
    );
    expect(card().textContent).toContain("Release checklist reminder");
    expect(
      screen.getByTestId("scheduled-task-card-schedule").textContent,
    ).toContain("Weekdays at 09:00 (Asia/Shanghai)");
    const stops = screen.getByTestId("scheduled-task-card-stops");
    expect(stops.textContent).toContain("every item is checked, pauses itself");
    expect(card().textContent).toContain("Safety cap: 60 runs");
    expect(card().textContent).toContain("Each run opens a new chat");
    expect(card().textContent).toContain("Active");
    await waitFor(() => expect(api.fetchScheduledTask).toHaveBeenCalled());
    expectNoRawIdentifiers(card());
    expect(
      screen.getByRole("link", { name: /Open task/ })?.getAttribute("href"),
    ).toBe(`/workspace/scheduled-tasks?task_id=${TASK_ID}`);
  });

  test("renders natural Chinese copy", async () => {
    api.fetchScheduledTask.mockResolvedValue(
      liveTask({ title: "发布清单提醒", stop_condition: "清单全部勾完" }),
    );
    renderCard(
      toolResult({
        task: {
          ...toolResult().task,
          title: "发布清单提醒",
          stop_condition: "清单全部勾完",
        },
      }),
      "zh-CN",
    );
    await waitFor(() => expect(card().textContent).toContain("工作日 09:00"));
    expect(card().textContent).toContain("清单全部勾完，满足后自动暂停");
    expect(card().textContent).toContain("保险上限：60 次");
    expect(card().textContent).toContain("立即试运行");
    expectNoRawIdentifiers(card());
  });

  test("a recurring task mid-run disables Pause and Run once now", async () => {
    api.fetchScheduledTask.mockResolvedValue(
      liveTask({ status: "enabled", active_run_status: "running" }),
    );
    renderCard();
    await waitFor(() => expect(card().textContent).toContain("Running now"));
    expect(button(/Run once now/)).toHaveProperty("disabled", true);
    expect(button(/Pause/)).toHaveProperty("disabled", true);
  });

  test("a queued run disables Run once now with the already-waiting reason", async () => {
    api.fetchScheduledTask.mockResolvedValue(
      liveTask({ active_run_status: "queued" }),
    );
    renderCard();
    await waitFor(() =>
      expect(button(/Run once now/)).toHaveProperty("disabled", true),
    );
    expect(
      button(/Run once now/)
        .closest("[data-disabled-reason]")
        ?.getAttribute("data-disabled-reason"),
    ).toBe("A run is already waiting to start");
    expect(button(/Pause/)).toHaveProperty("disabled", false);
  });

  test("an off-screen card does not poll; it refreshes when it scrolls into view", async () => {
    IntersectionObserverMock.visible = false;
    rs.useFakeTimers({ toFake: ["setTimeout", "setInterval", "Date"] });
    api.fetchScheduledTask.mockResolvedValue(liveTask());
    renderCard();
    await act(async () => {
      await rs.advanceTimersByTimeAsync(100);
    });
    const afterMount = api.fetchScheduledTask.mock.calls.length;
    await act(async () => {
      await rs.advanceTimersByTimeAsync(60_000);
    });
    expect(api.fetchScheduledTask).toHaveBeenCalledTimes(afterMount);

    await act(async () => {
      IntersectionObserverMock.instances.forEach((observer) =>
        observer.emit(true),
      );
      await rs.advanceTimersByTimeAsync(100);
    });
    expect(api.fetchScheduledTask.mock.calls.length).toBeGreaterThan(
      afterMount,
    );
    const inView = api.fetchScheduledTask.mock.calls.length;
    await act(async () => {
      await rs.advanceTimersByTimeAsync(31_000);
    });
    expect(api.fetchScheduledTask.mock.calls.length).toBeGreaterThan(inView);
  });

  test("Run once now triggers once, disables while pending, then links the trial chat", async () => {
    api.fetchScheduledTask.mockResolvedValue(liveTask());
    let resolveTrigger: (value: unknown) => void = () => undefined;
    api.triggerScheduledTask.mockReturnValue(
      new Promise((resolve) => {
        resolveTrigger = resolve;
      }),
    );
    renderCard();
    await waitFor(() => expect(api.fetchScheduledTask).toHaveBeenCalled());
    fireEvent.click(button(/Run once now/));
    fireEvent.click(button(/Run once now/));
    await waitFor(() =>
      expect(button(/Run once now/)).toHaveProperty("disabled", true),
    );
    expect(api.triggerScheduledTask).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveTrigger({
        id: TASK_ID,
        triggered: true,
        outcome: "launched",
        existing: false,
        thread_id: THREAD_ID,
      });
    });
    const trial = await screen.findByTestId("scheduled-task-card-trial");
    expect(trial.textContent).toContain("Trial run started");
    expect(
      screen.getByRole("link", { name: "Open chat" })?.getAttribute("href"),
    ).toBe(`/workspace/chats/${THREAD_ID}`);
  });

  test("a task paused by the agent reads Paused by agent and offers Resume", async () => {
    api.fetchScheduledTask.mockResolvedValue(
      liveTask({
        status: "paused",
        last_error:
          "stopped by the agent in run 41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
        last_run_id: "41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
        last_run_at: "2026-10-05T12:21:53+00:00",
      }),
    );
    renderCard();
    await waitFor(() =>
      expect(card().textContent).toContain("Paused by agent"),
    );
    expect(button(/Resume/)).toHaveProperty("disabled", false);
    expect(screen.queryByRole("button", { name: /Pause/ })).toBeNull();
    expect(
      screen.getByTestId("scheduled-task-card-stops").textContent,
    ).toContain("Reached");
    expectNoRawIdentifiers(card());
  });

  test("a trial after the agent paused the task never shows as the moment it was reached", async () => {
    api.fetchScheduledTask.mockResolvedValue(
      liveTask({
        status: "paused",
        stop_condition: "every item is checked",
        last_error:
          "stopped by the agent in run 41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
        // "Run once now" on the paused task moved the last run.
        last_run_id: "9b1c7f8e-1111-4c4c-9c9c-000000000001",
        last_run_at: "2026-10-06T08:00:00+00:00",
      }),
    );
    renderCard();
    await waitFor(() =>
      expect(card().textContent).toContain("Paused by agent"),
    );
    expect(
      screen.getByTestId("scheduled-task-card-stops").textContent,
    ).not.toContain("Reached");
  });

  test("resume with exhausted limits explains inline and links the task", async () => {
    api.fetchScheduledTask.mockResolvedValue(
      liveTask({ status: "completed", automatic_runs_used: 60 }),
    );
    api.resumeScheduledTask.mockRejectedValue(
      new GatewayApiError({
        message: "All 60 automatic runs are used.",
        status: 409,
        code: "limits_exhausted",
        params: { limit: "max_runs", used: 60, max_runs: 60, end_at: null },
        rawMessage: "All 60 automatic runs are used.",
      }),
    );
    renderCard();
    await waitFor(() =>
      expect(button(/Resume/)).toHaveProperty("disabled", false),
    );
    fireEvent.click(button(/Resume/));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("All 60 automatic runs are used");
    expect(alert.querySelector("a")?.getAttribute("href")).toBe(
      `/workspace/scheduled-tasks?task_id=${TASK_ID}`,
    );
  });

  test("a 404 shows the deleted state", async () => {
    api.fetchScheduledTask.mockRejectedValue(
      new GatewayApiError({
        message: "Scheduled task not found",
        status: 404,
        code: "task_not_found",
        params: {},
        rawMessage: "Scheduled task not found",
      }),
    );
    renderCard();
    await waitFor(() =>
      expect(card()?.getAttribute("data-state")).toBe("deleted"),
    );
    expect(card().textContent).toContain("This task was deleted.");
    expect(screen.queryByRole("button")).toBeNull();
  });

  test("a delete result renders deleted without fetching", () => {
    renderCard(
      toolResult({
        action: "delete",
        task: { id: TASK_ID, title: "Release checklist reminder" },
      }),
    );
    expect(card().textContent).toContain("This task was deleted.");
    expect(api.fetchScheduledTask).not.toHaveBeenCalled();
  });

  test("shows the scheduler-off line", async () => {
    feature.value = { ...feature.value, running: false };
    api.fetchScheduledTask.mockResolvedValue(liveTask());
    renderCard();
    expect(
      screen.getByTestId("scheduled-task-card-scheduler-off").textContent,
    ).toContain(
      "Automatic runs are off on this server, so this task won't run on schedule.",
    );
    await waitFor(() => expect(api.fetchScheduledTask).toHaveBeenCalled());
  });
});
