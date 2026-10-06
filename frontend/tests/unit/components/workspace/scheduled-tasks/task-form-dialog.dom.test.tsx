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

  test("a goal with reuse-thread runs is rejected", () => {
    const { state } = initialFormState({ mode: "edit", task: task() }, "");
    expect(
      validateForm({ ...state, contextMode: "reuse_thread", chatId: "c-1" }),
    ).toEqual({ ok: false, error: "goalNeedsFresh" });
  });
});
