import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import {
  createPayload,
  TaskFormDialog,
  updatePayload,
  validateForm,
  initialFormState,
  type TaskFormRequest,
} from "@/components/workspace/scheduled-tasks/task-form-dialog";
import { I18nProvider } from "@/core/i18n/context";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

const { createTask, updateTask } = rs.hoisted(() => ({
  createTask: rs.fn(),
  updateTask: rs.fn(),
}));

rs.mock("@/core/scheduled-tasks/api", () => ({
  createScheduledTask: createTask,
  updateScheduledTask: updateTask,
}));
rs.mock("@/core/agents/api", () => ({
  fetchAgentsApiEnabled: async () => false,
  listAgents: async () => [],
}));
rs.mock("sonner", () => ({
  toast: { success: rs.fn(), error: rs.fn(), info: rs.fn() },
}));

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  createTask.mockReset();
  updateTask.mockReset();
  document.cookie = "locale=; max-age=0; path=/";
});

function task(overrides: Partial<ScheduledTask> = {}): ScheduledTask {
  return {
    id: "task-1",
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    assistant_id: null,
    title: "Checklist",
    prompt: "List the open items",
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
    goal_objective: "status.md lists the open items",
    max_runs: 10,
    end_at: "2099-12-31T10:00:00Z",
    stop_condition: "every item is checked",
    automatic_runs_used: 4,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderForm(
  request: TaskFormRequest,
  {
    locale = "en-US",
    toolEnabled = true,
  }: { locale?: "en-US" | "zh-CN"; toolEnabled?: boolean } = {},
) {
  document.cookie = `locale=${locale}; path=/`;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <TaskFormDialog
          request={request}
          toolEnabled={toolEnabled}
          onOpenChange={rs.fn()}
        />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("TaskFormDialog", () => {
  test("every field resolves by its label", () => {
    renderForm({ mode: "edit", task: task() });
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveProperty(
      "value",
      "Checklist",
    );
    expect(
      screen.getByRole("textbox", {
        name: "Instructions",
      }),
    ).toHaveProperty("value", "List the open items");
    expect(
      screen.getByRole("textbox", {
        name: "Stops when (optional)",
      }),
    ).toHaveProperty("value", "every item is checked");
    expect(
      screen.getByRole("textbox", {
        name: "Each run's goal (optional)",
      }),
    ).toHaveProperty("value", "status.md lists the open items");
    expect(
      screen.getByRole("spinbutton", {
        name: "Safety cap: number of runs",
      }),
    ).toHaveProperty("value", "10");
    expect(screen.getByLabelText("Safety cap: end by (UTC)")).toBeTruthy();
    expect(
      screen.getByText(
        "Automatic runs over the task's lifetime; trial runs excluded. 4 used so far.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Edit task" })).toBeTruthy();
  });

  test("a duplicate keeps the cap but starts its run count at zero", () => {
    renderForm({ mode: "duplicate", task: task() });
    expect(
      screen.getByRole("spinbutton", { name: "Safety cap: number of runs" }),
    ).toHaveProperty("value", "10");
    expect(
      screen.getByText(
        "Automatic runs over the task's lifetime; trial runs excluded. 0 used so far.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "New scheduled task" }),
    ).toBeTruthy();
  });

  test("Chinese labels use the glossary", () => {
    renderForm({ mode: "create" }, { locale: "zh-CN" });
    for (const name of [
      "标题",
      "任务指令",
      "何时停止（可选）",
      "每次运行的目标（可选）",
    ]) {
      expect(screen.getByRole("textbox", { name })).toBeTruthy();
    }
    expect(
      screen.getByRole("spinbutton", { name: "保险上限：运行次数" }),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "新建定时任务" })).toBeTruthy();
  });

  test("the stop condition field is hidden while the chat tool is off", () => {
    renderForm({ mode: "create" }, { toolEnabled: false });
    expect(
      screen.queryByRole("textbox", { name: "Stops when (optional)" }),
    ).toBeNull();
  });

  test("clearing the run limit and stop condition sends null, and nothing else", async () => {
    updateTask.mockResolvedValue(
      task({ max_runs: null, stop_condition: null }),
    );
    renderForm({ mode: "edit", task: task() });
    fireEvent.click(
      screen.getByRole("button", { name: "Clear Safety cap: number of runs" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "Stops when (optional)" }),
      { target: { value: "   " } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith("task-1", {
      max_runs: null,
      stop_condition: null,
    });
  });

  test("a title-only edit leaves a cron the schedule input reorders alone", async () => {
    // The input shows "0 09 * * 0,6" as weekly Sat+Sun and emits
    // "0 9 * * 6,0"; re-sending it would re-arm (or refuse) a finished task.
    const source = task({
      status: "completed",
      schedule_spec: { cron: "0 09 * * 0,6" },
    });
    updateTask.mockResolvedValue({ ...source, title: "Weekend check" });
    renderForm({ mode: "edit", task: source });
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), {
      target: { value: "Weekend check" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith("task-1", {
      title: "Weekend check",
    });
  });

  test("a title-only edit leaves an end time in a repeated hour alone", async () => {
    // 06:30Z is the second 01:30 of the New York fall-back; the field shows
    // 01:30, which alone would read as the first one (05:30Z).
    const source = task({
      timezone: "America/New_York",
      end_at: "2026-11-01T06:30:00Z",
    });
    updateTask.mockResolvedValue({ ...source, title: "Checklist v2" });
    renderForm({ mode: "edit", task: source });
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), {
      target: { value: "Checklist v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith("task-1", {
      title: "Checklist v2",
    });
  });

  test("a duplicate keeps the stop condition even while its field is hidden", async () => {
    createTask.mockResolvedValue(task({ id: "task-2" }));
    renderForm({ mode: "duplicate", task: task() }, { toolEnabled: false });
    expect(
      screen.queryByRole("textbox", { name: "Stops when (optional)" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
    expect(createTask.mock.calls[0]![0]).toMatchObject({
      title: "Checklist (copy)",
      stop_condition: "every item is checked",
      goal_objective: "status.md lists the open items",
      max_runs: 10,
    });
  });

  test("switching to an existing chat leaves a goal clearable, then saves", async () => {
    updateTask.mockResolvedValue(task());
    renderForm({ mode: "edit", task: task() });
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    const where = screen.getByRole("group", { name: "Where runs happen" });
    expect(where).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Run in an existing chat" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Chat ID" }), {
      target: { value: "chat-1" },
    });
    const goal = screen.getByRole("textbox", {
      name: "Each run's goal (optional)",
    });
    expect(goal).toHaveProperty("disabled", false);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      screen.getByText("A goal needs each run to start a new chat.", {
        selector: "p[role=alert]",
      }),
    ).toBeTruthy();
    fireEvent.change(goal, { target: { value: "" } });
    expect(goal).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]![1]).toMatchObject({
      context_mode: "reuse_thread",
      thread_id: "chat-1",
      goal_objective: null,
    });
  });

  test("a non-existent end time names the end time, not the schedule", () => {
    renderForm({ mode: "edit", task: task({ timezone: "America/New_York" }) });
    fireEvent.change(
      screen.getByLabelText("Safety cap: end by (America/New_York)"),
      // Spring forward: 02:30 does not exist in New York that morning.
      { target: { value: "2099-03-08T02:30" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByRole("alert").textContent).toBe(
      "This end time does not exist in the selected timezone. Choose another time.",
    );
    expect(updateTask).not.toHaveBeenCalled();
  });

  test("Chinese field labels put the zone in full-width parentheses", () => {
    renderForm({ mode: "create" }, { locale: "zh-CN" });
    fireEvent.click(screen.getByRole("button", { name: "高级选项" }));
    expect(screen.getByRole("group", { name: "运行位置" })).toBeTruthy();
    expect(screen.getByText(/^保险上限：结束时间（.+）$/)).toBeTruthy();
  });

  test("an invalid run limit is refused before any request", () => {
    renderForm({ mode: "edit", task: task() });
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Safety cap: number of runs" }),
      { target: { value: "0" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByRole("alert").textContent).toBe(
      "The run limit must be a whole number of at least 1.",
    );
    expect(updateTask).not.toHaveBeenCalled();
  });
});

describe("form payload helpers", () => {
  test("an untouched form produces an empty update", () => {
    const source = task({ end_at: "2099-12-31T10:00:30Z" });
    const { state } = initialFormState(
      { mode: "edit", task: source },
      "(copy)",
    );
    const valid = validateForm(state);
    expect(valid.ok).toBe(true);
    if (!valid.ok) return;
    expect(
      updatePayload(source, state, valid, { includeStopCondition: true }),
    ).toEqual({});
  });

  test("duplicate drops a passed end time and copies everything else", () => {
    const { state, endAtDropped } = initialFormState(
      {
        mode: "duplicate",
        task: task({ end_at: "2020-01-01T00:00:00Z", assistant_id: "bot" }),
      },
      "（副本）",
    );
    expect(endAtDropped).toBe(true);
    expect(state.endAtLocal).toBe("");
    expect(state.title).toBe("Checklist（副本）");
    expect(state.goal).toBe("status.md lists the open items");
    expect(state.stopCondition).toBe("every item is checked");
    expect(state.maxRuns).toBe("10");
    expect(state.assistantId).toBe("bot");
  });

  test.each([
    ["0 9 * * 6,0", false],
    ["0 9 * * 7,6", false],
    ["0 10 * * 6,0", true],
    ["0 9 * * 6", true],
  ])(
    "a stored 0 09 * * 0,6 edited to %s sends the schedule: %s",
    (cron, sent) => {
      const source = task({ schedule_spec: { cron: "0 09 * * 0,6" } });
      const { state } = initialFormState({ mode: "edit", task: source }, "");
      const edited = {
        ...state,
        schedule: { ...state.schedule, schedule_spec: { cron } },
      };
      const valid = validateForm(edited, source.end_at);
      expect(valid.ok).toBe(true);
      if (!valid.ok) return;
      const updates = updatePayload(source, edited, valid, {
        includeStopCondition: true,
      });
      expect("schedule_spec" in updates).toBe(sent);
    },
  );

  test("duplicate copies an end time in a repeated hour as the same instant", () => {
    const source = task({
      timezone: "America/New_York",
      end_at: "2026-11-01T06:30:00Z",
    });
    const { state } = initialFormState(
      { mode: "duplicate", task: source },
      "(copy)",
      new Date("2026-10-06T00:00:00Z"),
    );
    expect(state.endAtLocal).toBe("2026-11-01T01:30");
    const valid = validateForm(state, source.end_at);
    expect(valid.ok).toBe(true);
    if (!valid.ok) return;
    expect(createPayload(state, valid).end_at).toBe("2026-11-01T06:30:00Z");
  });

  test("a goal with reuse-thread runs is rejected", () => {
    const { state } = initialFormState({ mode: "edit", task: task() }, "");
    expect(
      validateForm({ ...state, contextMode: "reuse_thread", chatId: "c-1" }),
    ).toEqual({ ok: false, error: "goalNeedsFresh" });
  });
});
