import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, type MockScheduledTask } from "./utils/mock-api";

const group = {
  id: "feishu-group-binding",
  provider: "feishu",
  status: "connected",
  workspace_id: "oc_hidden_group",
  workspace_name: "Planning team",
  scopes: [],
  metadata: { chat_id: "oc_hidden_group", chat_type: "group" },
};

function task(overrides: Partial<MockScheduledTask> = {}): MockScheduledTask {
  return {
    id: "group-notification-task",
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    title: "Team summary",
    prompt: "Summarize this week's decisions",
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
    status: "enabled",
    next_run_at: "2099-01-01T09:00:00Z",
    last_run_at: null,
    last_run_id: null,
    last_error: null,
    run_count: 0,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

async function open(
  page: Page,
  source: MockScheduledTask,
  failConnections = false,
  supportsGroups = true,
) {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [source],
    features: { scheduledTasks: { groupNotifications: supportsGroups } },
  });
  await page.route("**/api/channels/connections", (route) =>
    route.fulfill({
      status: failConnections ? 503 : 200,
      contentType: "application/json",
      body: JSON.stringify(
        failConnections
          ? { detail: "Unavailable" }
          : {
              connections: [
                group,
                { ...group, id: "unnamed-binding", workspace_name: null },
                {
                  ...group,
                  id: "personal-binding",
                  workspace_name: "Private chat",
                  metadata: { ...group.metadata, chat_type: "p2p" },
                },
              ],
            },
      ),
    }),
  );
  await page.goto(`/workspace/scheduled-tasks?task_id=${source.id}`);
  await expect(page.getByTestId("scheduled-task-detail")).toBeVisible();
}

test("selecting and clearing an additional group preserves the schedule and displays its name", async ({
  page,
}) => {
  const source = task();
  await open(page, source);
  const requests: unknown[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "PATCH" &&
      new URL(request.url()).pathname === `/api/scheduled-tasks/${source.id}`
    )
      requests.push(request.postDataJSON());
  });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const form = page.getByTestId("scheduled-task-form");
  const select = form.getByRole("combobox", {
    name: "Also notify a group (optional)",
  });
  await expect(select).toHaveText("No additional group");
  await select.click();
  await expect(page.getByRole("option", { name: "Private chat" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("option", { name: "Group name unavailable" }),
  ).toBeDisabled();
  await page
    .getByRole("option", { name: "Planning team", exact: true })
    .click();
  await form.getByRole("button", { name: "Save changes" }).click();
  await expect(form).toHaveCount(0);
  expect(requests).toEqual([{ notification_group_connection_id: group.id }]);
  await expect(
    page.getByTestId("scheduled-task-notification-group"),
  ).toContainText("Planning team");
  await page.reload();
  await expect(
    page.getByTestId("scheduled-task-notification-group"),
  ).toContainText("Planning team");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await form
    .getByRole("combobox", { name: "Also notify a group (optional)" })
    .click();
  await page
    .getByRole("option", { name: "No additional group", exact: true })
    .click();
  await form.getByRole("button", { name: "Save changes" }).click();
  await expect(form).toHaveCount(0);
  expect(requests).toEqual([
    { notification_group_connection_id: group.id },
    { notification_group_connection_id: null },
  ]);
  await expect(
    page.getByTestId("scheduled-task-notification-group"),
  ).toHaveCount(0);
});

test("a connection-list failure does not clear an existing group when saving another field", async ({
  page,
}) => {
  const source = task({
    notification_group_connection_id: "missing-group-binding",
  });
  await open(page, source, true);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const form = page.getByTestId("scheduled-task-form");
  // The real connections query retries 503s before exposing its error state.
  // Wait through that backoff; preserving a selection while merely loading
  // would not exercise the failed-query behavior this case is meant to pin.
  await expect(
    form.getByText(
      "Could not load groups. Your selection is kept; you can save other changes or remove it.",
    ),
  ).toBeVisible({ timeout: 15_000 });
  await expect(
    form.getByRole("combobox", {
      name: "Also notify a group (optional)",
    }),
  ).toHaveText("Selected group unavailable");
  await expect(form).not.toContainText("missing-group-binding");
  await form
    .getByRole("textbox", { name: "Title", exact: true })
    .fill("Updated team summary");
  const request = page.waitForRequest(
    (r) =>
      r.method() === "PATCH" &&
      new URL(r.url()).pathname === `/api/scheduled-tasks/${source.id}`,
  );
  await form.getByRole("button", { name: "Save changes" }).click();
  expect((await request).postDataJSON()).toEqual({
    title: "Updated team summary",
  });
});

test("duplicating a task copies its selected group", async ({ page }) => {
  const source = task({ notification_group_connection_id: group.id });
  await open(page, source);
  await page
    .getByTestId("scheduled-task-detail")
    .getByRole("button", { name: "More actions" })
    .click();
  await page.getByRole("menuitem", { name: "Duplicate" }).click();
  const form = page.getByTestId("scheduled-task-form");
  await expect(
    form.getByRole("combobox", {
      name: "Also notify a group (optional)",
    }),
  ).toHaveText("Planning team");
  const request = page.waitForRequest(
    (r) =>
      r.method() === "POST" &&
      new URL(r.url()).pathname === "/api/scheduled-tasks",
  );
  await form.getByRole("button", { name: "Create", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({
    notification_group_connection_id: group.id,
    schedule_spec: source.schedule_spec,
  });
});

test("the task form provides a persistent group binding command and refreshes the resulting group", async ({
  page,
}) => {
  await page.addInitScript(() => {
    let copied = "";
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          copied = text;
        },
        readText: async () => copied,
      },
    });
  });
  let groupBound = false;
  let codesCreated = 0;
  await open(page, task());
  await page.route("**/api/channels/connections", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ connections: groupBound ? [group] : [] }),
    }),
  );
  await page.route("**/api/channels/feishu/connect", (route) => {
    codesCreated++;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provider: "feishu",
        mode: "binding_code",
        code: "test-group-binding-code",
        expires_in: 600,
        instruction: "Send /connect test-group-binding-code",
        url: null,
      }),
    });
  });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const form = page.getByTestId("scheduled-task-form");
  await form
    .getByRole("button", { name: "Bind a Feishu group", exact: true })
    .click();
  const binding = form.getByTestId("feishu-group-binding");
  await expect(
    binding.getByRole("textbox", { name: "Group binding command" }),
  ).toHaveValue("/connect test-group-binding-code");
  await binding
    .getByRole("button", { name: "Copy command", exact: true })
    .click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "/connect test-group-binding-code",
  );
  await binding
    .getByRole("button", { name: "Close binding instructions" })
    .click();
  await form
    .getByRole("button", { name: "Bind a Feishu group", exact: true })
    .click();
  await expect(
    binding.getByRole("textbox", { name: "Group binding command" }),
  ).toHaveValue("/connect test-group-binding-code");
  expect(codesCreated).toBe(1);
  groupBound = true;
  await form.getByRole("button", { name: "Refresh group list" }).click();
  const selector = form.getByRole("combobox", {
    name: "Also notify a group (optional)",
  });
  await expect(selector).toHaveText("No additional group");
  await selector.click();
  await expect(
    page.getByRole("option", { name: "Planning team" }),
  ).toBeVisible();
});

test("a backend without the group capability does not offer a group destination", async ({
  page,
}) => {
  await open(page, task(), false, false);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const form = page.getByTestId("scheduled-task-form");
  await expect(
    form.getByRole("button", { name: "Bind a Feishu group" }),
  ).toHaveCount(0);
  await expect(
    form.getByRole("combobox", {
      name: "Also notify a group (optional)",
    }),
  ).toHaveCount(0);
});
