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
import type { ChannelConnection } from "@/core/channels/types";
import { I18nProvider } from "@/core/i18n/context";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

function group(overrides: Partial<ChannelConnection> = {}): ChannelConnection {
  return {
    id: "group-binding",
    provider: "feishu",
    status: "connected",
    workspace_id: "oc_private_group_id",
    workspace_name: "Planning team",
    metadata: { chat_id: "oc_private_group_id", chat_type: "group" },
    scopes: [],
    ...overrides,
  };
}

const {
  createTask,
  updateTask,
  listConnections,
  connectProvider,
  groupNotifications,
} = rs.hoisted(() => ({
  createTask: rs.fn(),
  updateTask: rs.fn(),
  listConnections: rs.fn(async (): Promise<ChannelConnection[]> => []),
  connectProvider: rs.fn(),
  groupNotifications: { value: true as boolean | undefined, isLoading: false },
}));

rs.mock("@/core/scheduled-tasks/api", () => ({
  createScheduledTask: createTask,
  updateScheduledTask: updateTask,
}));
rs.mock("@/core/agents/api", () => ({
  fetchAgentsApiEnabled: async () => false,
  listAgents: async () => [],
}));
rs.mock("@/core/channels/api", () => ({
  listChannelConnections: listConnections,
  connectChannelProvider: connectProvider,
}));
rs.mock("@/core/features/hooks", () => ({
  useScheduledTasksFeature: () => ({
    groupNotifications: groupNotifications.value,
    isLoading: groupNotifications.isLoading,
  }),
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
  listConnections.mockReset();
  listConnections.mockResolvedValue([]);
  connectProvider.mockReset();
  groupNotifications.value = true;
  groupNotifications.isLoading = false;
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
  const tree = () => (
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <TaskFormDialog
          request={request}
          toolEnabled={toolEnabled}
          onOpenChange={rs.fn()}
        />
      </I18nProvider>
    </QueryClientProvider>
  );
  const view = render(tree());
  return { ...view, rerenderForm: () => view.rerender(tree()) };
}

describe("TaskFormDialog", () => {
  test("a pending capability preserves the saved group through a title edit and then shows the enabled selector", async () => {
    groupNotifications.value = false;
    groupNotifications.isLoading = true;
    listConnections.mockResolvedValue([group()]);
    updateTask.mockResolvedValue(task());
    const view = renderForm({
      mode: "edit",
      task: task({ notification_group_connection_id: "group-binding" }),
    });

    expect(screen.getByText("Loading groups…")).toBeTruthy();
    expect(
      screen.queryByText(
        "This task has a saved group destination, but group notifications are unavailable on this server.",
      ),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Clear group notification" }),
    ).toBeNull();
    expect(
      screen.queryByRole("combobox", {
        name: "Also notify a group (optional)",
      }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Bind a Feishu group" }),
    ).toBeNull();
    expect(listConnections).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), {
      target: { value: "Updated title" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith("task-1", {
        title: "Updated title",
      }),
    );

    groupNotifications.value = true;
    groupNotifications.isLoading = false;
    view.rerenderForm();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", {
          name: "Also notify a group (optional)",
        }).textContent,
      ).toBe("Planning team"),
    );
    expect(
      screen.queryByRole("button", { name: "Clear group notification" }),
    ).toBeNull();
  });

  test("a saved group can be explicitly cleared only after the capability resolves as disabled", async () => {
    groupNotifications.value = false;
    groupNotifications.isLoading = true;
    updateTask.mockResolvedValue(task());
    const view = renderForm({
      mode: "edit",
      task: task({ notification_group_connection_id: "group-binding" }),
    });

    expect(screen.getByText("Loading groups…")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Clear group notification" }),
    ).toBeNull();
    groupNotifications.isLoading = false;
    view.rerenderForm();

    expect(
      screen.getByText(
        "This task has a saved group destination, but group notifications are unavailable on this server.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Clear group notification" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith("task-1", {
        notification_group_connection_id: null,
      }),
    );
    expect(listConnections).not.toHaveBeenCalled();
  });

  test.each([
    [
      "en-US",
      "This task has a saved group destination, but group notifications are unavailable on this server.",
      "Clear group notification",
      "Create",
    ],
    ["zh-CN", "已有群通知配置，当前服务未启用群通知。", "清除群通知", "创建"],
  ] as const)(
    "a duplicate can explicitly drop an old group when the capability is off (%s)",
    async (locale, notice, clear, create) => {
      groupNotifications.value = false;
      createTask.mockResolvedValue(task({ id: "task-copy" }));
      renderForm(
        {
          mode: "duplicate",
          task: task({ notification_group_connection_id: "existing-binding" }),
        },
        { locale },
      );
      expect(screen.getByText(notice)).toBeTruthy();
      expect(document.body.textContent).not.toContain("existing-binding");
      expect(listConnections).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: clear }));
      fireEvent.click(screen.getByRole("button", { name: create }));
      await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
      expect(createTask.mock.calls[0]![0]).not.toHaveProperty(
        "notification_group_connection_id",
      );
      expect(createTask.mock.calls[0]![0]).toMatchObject({
        schedule_spec: { cron: "0 9 * * *" },
      });
    },
  );

  test("clearing a saved group with the capability off sends only null in an edit", async () => {
    groupNotifications.value = false;
    updateTask.mockResolvedValue(task());
    renderForm({
      mode: "edit",
      task: task({ notification_group_connection_id: "existing-binding" }),
    });
    expect(
      screen.queryByRole("button", { name: "Bind a Feishu group" }),
    ).toBeNull();
    expect(
      screen.queryByRole("combobox", {
        name: "Also notify a group (optional)",
      }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Clear group notification" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith("task-1", {
        notification_group_connection_id: null,
      }),
    );
  });

  test("an older backend without the group capability hides selection and binding while preserving the saved field", async () => {
    groupNotifications.value = undefined;
    updateTask.mockResolvedValue(task());
    renderForm({
      mode: "edit",
      task: task({ notification_group_connection_id: "existing-binding" }),
    });
    expect(
      screen.queryByRole("combobox", {
        name: "Also notify a group (optional)",
      }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Bind a Feishu group" }),
    ).toBeNull();
    expect(listConnections).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), {
      target: { value: "Updated title" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith("task-1", {
        title: "Updated title",
      }),
    );
  });

  test("group binding keeps a copyable command visible without changing the saved destination", async () => {
    connectProvider.mockResolvedValue({
      provider: "feishu",
      mode: "binding_code",
      code: "test-group-code",
      instruction: "unused",
      expires_in: 600,
    });
    const writeText = rs.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    updateTask.mockResolvedValue(task());
    renderForm({
      mode: "edit",
      task: task({ notification_group_connection_id: "saved-group-binding" }),
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Bind a Feishu group" }),
    );
    const command = await screen.findByRole("textbox", {
      name: "Group binding command",
    });
    expect(command).toHaveProperty("value", "/connect test-group-code");
    expect(command).toHaveProperty("readOnly", true);
    expect(connectProvider).toHaveBeenCalledWith("feishu");
    expect(
      screen.getByText(
        "Add the bot to the group, then mention the bot and send this command in that group. Refresh the group list after binding.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("/connect test-group-code"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Close binding instructions" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), {
      target: { value: "Checklist v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith("task-1", {
        title: "Checklist v2",
      }),
    );
  });

  test("WeCom and QQ group bind buttons request provider-specific binding codes", async () => {
    connectProvider.mockImplementation(async (provider: string) => ({
      provider,
      mode: "binding_code",
      code: `${provider}-group-code`,
      instruction: "unused",
      expires_in: 600,
    }));
    renderForm({ mode: "create" });

    fireEvent.click(screen.getByRole("button", { name: "Bind a WeCom group" }));
    fireEvent.change(
      await screen.findByRole("textbox", { name: "Group name" }),
      {
        target: { value: "Release team" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Generate a new code" }),
    );
    const command = await screen.findByRole("textbox", {
      name: "Group binding command",
    });
    await waitFor(() =>
      expect(command).toHaveProperty("value", "/connect wecom-group-code"),
    );
    expect(connectProvider).toHaveBeenCalledWith("wecom", {
      groupName: "Release team",
    });

    fireEvent.click(screen.getByRole("button", { name: "Bind a QQ group" }));
    expect(screen.getByRole("textbox", { name: "Group name" })).toHaveProperty(
      "value",
      "",
    );
    expect(
      screen.queryByRole("textbox", { name: "Group binding command" }),
    ).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), {
      target: { value: "Support team" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Generate a new code" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: "Group binding command" }),
      ).toHaveProperty("value", "/connect qq-group-code"),
    );
    expect(connectProvider).toHaveBeenCalledWith("qq", {
      groupName: "Support team",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Bind a Feishu group" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: "Group binding command" }),
      ).toHaveProperty("value", "/connect feishu-group-code"),
    );
    expect(screen.queryByRole("textbox", { name: "Group name" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Bind a WeCom group" }));
    expect(
      screen.getByRole("textbox", { name: "Group binding command" }),
    ).toHaveProperty("value", "/connect wecom-group-code");
    expect(connectProvider).toHaveBeenCalledTimes(3);
    fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), {
      target: { value: "Operations" },
    });
    expect(
      screen.queryByRole("textbox", { name: "Group binding command" }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Generate a new code" }),
    );
    await waitFor(() =>
      expect(connectProvider).toHaveBeenLastCalledWith("wecom", {
        groupName: "Operations",
      }),
    );
    await screen.findByRole("textbox", { name: "Group binding command" });
  });

  test("refreshing after binding discovers the group without changing the task automatically", async () => {
    listConnections.mockResolvedValueOnce([]).mockResolvedValue([group()]);
    renderForm({ mode: "create" });
    await screen.findByText("Bind a group below, then refresh the list.");
    fireEvent.click(screen.getByRole("button", { name: "Refresh group list" }));
    await waitFor(() => expect(listConnections).toHaveBeenCalledTimes(2));
    fireEvent.keyDown(
      screen.getByRole("combobox", {
        name: "Also notify a group (optional)",
      }),
      { key: "ArrowDown" },
    );
    expect(
      await screen.findByRole("option", { name: "Planning team" }),
    ).toBeTruthy();
    expect(createTask).not.toHaveBeenCalled();
    expect(updateTask).not.toHaveBeenCalled();
  });

  test("choosing a named Feishu group sends only the new destination", async () => {
    listConnections.mockResolvedValue([group()]);
    updateTask.mockResolvedValue(task());
    renderForm({ mode: "edit", task: task() });
    await waitFor(() => expect(listConnections).toHaveBeenCalled());
    fireEvent.keyDown(
      screen.getByRole("combobox", {
        name: "Also notify a group (optional)",
      }),
      { key: "ArrowDown" },
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "Planning team" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith("task-1", {
      notification_group_connection_id: "group-binding",
    });
  });

  test("a failed groups query preserves the stored destination when editing another field", async () => {
    listConnections.mockRejectedValue(new Error("offline"));
    updateTask.mockResolvedValue(task());
    renderForm({
      mode: "edit",
      task: task({ notification_group_connection_id: "saved-group-binding" }),
    });
    await screen.findByText(
      "Could not load groups. Your selection is kept; you can save other changes or remove it.",
    );
    expect(
      screen.getByRole("combobox", {
        name: "Also notify a group (optional)",
      }).textContent,
    ).toBe("Selected group unavailable");
    expect(document.body.textContent).not.toContain("saved-group-binding");
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), {
      target: { value: "Checklist v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith("task-1", {
      title: "Checklist v2",
    });
  });

  test("an unavailable selected group can be explicitly cleared even while the list fails", async () => {
    listConnections.mockRejectedValue(new Error("offline"));
    updateTask.mockResolvedValue(task());
    renderForm({
      mode: "edit",
      task: task({ notification_group_connection_id: "saved-group-binding" }),
    });
    await screen.findByText(
      "Could not load groups. Your selection is kept; you can save other changes or remove it.",
    );
    fireEvent.keyDown(
      screen.getByRole("combobox", {
        name: "Also notify a group (optional)",
      }),
      { key: "ArrowDown" },
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "No additional group" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith("task-1", {
      notification_group_connection_id: null,
    });
  });

  test("unnamed groups are disabled without exposing identifiers", async () => {
    listConnections.mockResolvedValue([group({ workspace_name: null })]);
    renderForm({ mode: "create" });
    await screen.findByText(
      "Bind the group again with a recognizable name before selecting it.",
    );
    fireEvent.keyDown(
      screen.getByRole("combobox", {
        name: "Also notify a group (optional)",
      }),
      { key: "ArrowDown" },
    );
    expect(
      (
        await screen.findByRole("option", { name: "Group name unavailable" })
      ).getAttribute("aria-disabled"),
    ).toBe("true");
    expect(document.body.textContent).not.toContain("oc_private_group_id");
    expect(document.body.textContent).not.toContain("group-binding");
  });

  test("the Chinese group field explains that personal notifications stay unchanged", async () => {
    renderForm({ mode: "create" }, { locale: "zh-CN" });
    expect(
      screen.getByRole("combobox", { name: "额外通知到群聊（可选）" })
        .textContent,
    ).toBe("仅通知本人");
    expect(
      screen.getByText("你现有的个人通知保持不变，所选群也会收到任务更新。"),
    ).toBeTruthy();
    await screen.findByText("先在下方绑定群聊，再刷新群列表。");
  });

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
  test("duplicate retains an additional group, while an untouched edit omits it", () => {
    const source = task({ notification_group_connection_id: "group-binding" });
    const { state } = initialFormState(
      { mode: "duplicate", task: source },
      "(copy)",
    );
    const valid = validateForm(state, source.end_at);
    expect(valid.ok).toBe(true);
    if (!valid.ok) return;
    expect(createPayload(state, valid).notification_group_connection_id).toBe(
      "group-binding",
    );
    expect(
      updatePayload(source, { ...state, title: source.title }, valid, {
        includeStopCondition: true,
      }),
    ).toEqual({});
  });

  test("changing only a notification group never sends the schedule; clearing sends null", () => {
    const source = task({ notification_group_connection_id: "old-binding" });
    const { state } = initialFormState({ mode: "edit", task: source }, "");
    const valid = validateForm(state, source.end_at);
    expect(valid.ok).toBe(true);
    if (!valid.ok) return;
    expect(
      updatePayload(
        source,
        { ...state, notificationGroupConnectionId: "new-binding" },
        valid,
        {
          includeStopCondition: true,
        },
      ),
    ).toEqual({ notification_group_connection_id: "new-binding" });
    expect(
      updatePayload(
        source,
        { ...state, notificationGroupConnectionId: "" },
        valid,
        {
          includeStopCondition: true,
        },
      ),
    ).toEqual({ notification_group_connection_id: null });
  });

  test("new tasks have no additional group by default", () => {
    const { state } = initialFormState({ mode: "create" }, "");
    expect(state.notificationGroupConnectionId).toBe("");
    expect(
      createPayload(state, { maxRuns: null, endAt: null })
        .notification_group_connection_id,
    ).toBeUndefined();
  });

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
