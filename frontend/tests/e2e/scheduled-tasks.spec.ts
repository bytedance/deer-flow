import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe.configure({ mode: "serial" });

test("scheduled tasks page is reachable from sidebar", async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-1",
        thread_id: "thread-1",
        title: "Daily summary",
        prompt: "Summarize thread",
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-07-02T01:00:00+00:00",
        last_run_at: null,
        last_run_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-07-01T00:00:00+00:00",
        updated_at: "2026-07-01T00:00:00+00:00",
      },
    ],
  });

  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: /scheduled tasks/i }).click();
  await page.waitForURL("**/workspace/scheduled-tasks");
  await expect(page).toHaveURL(/workspace\/scheduled-tasks/);
  await expect(
    page.getByRole("button", { name: /Daily summary/i }),
  ).toBeVisible();
  await expect(page.getByTestId("scheduled-task-runs")).toContainText("0 runs");
});

test("thread page links to filtered scheduled tasks", async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Thread with schedules",
        updated_at: "2025-06-01T12:00:00Z",
      },
    ],
    scheduledTasks: [
      {
        id: "task-1",
        thread_id: MOCK_THREAD_ID,
        title: "Thread task",
        prompt: "Summarize thread",
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-07-02T01:00:00+00:00",
        last_run_at: null,
        last_run_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-07-01T00:00:00+00:00",
        updated_at: "2026-07-01T00:00:00+00:00",
      },
    ],
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await page
    .locator("header")
    .getByRole("link", { name: /scheduled tasks/i })
    .click();
  await page.waitForURL(new RegExp(`thread_id=${MOCK_THREAD_ID}`));
});

test("user can create a scheduled task from the page", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [] });

  await page.goto("/workspace/scheduled-tasks");
  const createForm = page.getByTestId("scheduled-task-create-form");
  await createForm.getByRole("button", { name: "One-time" }).click();
  await createForm.getByLabel("Run at").fill("2026-07-02T09:00");
  await createForm.getByPlaceholder("Task title").fill("Created from UI");
  await createForm.getByPlaceholder("Prompt").fill("Summarize thread");
  await createForm.getByRole("button", { name: "Create" }).click();
  await expect(
    page.getByRole("button", { name: /Created from UI/i }),
  ).toBeVisible();
  await expect(
    page.getByTestId("scheduled-task-detail").getByText("Summarize thread"),
  ).toBeVisible();
});

test("user can pause a scheduled task from the detail pane", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-1",
        thread_id: "thread-1",
        title: "Pausable task",
        prompt: "Summarize thread",
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-07-02T01:00:00+00:00",
        last_run_at: null,
        last_run_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-07-01T00:00:00+00:00",
        updated_at: "2026-07-01T00:00:00+00:00",
      },
    ],
  });

  await page.goto("/workspace/scheduled-tasks");
  const detail = page.getByTestId("scheduled-task-detail");
  await detail.getByRole("button", { name: "Pause" }).click();
  await expect(page.getByTestId("scheduled-task-item-task-1")).toBeVisible();
  await expect(
    page.getByTestId("scheduled-task-item-task-1").getByText(/paused/i),
  ).toBeVisible();
});

test("trigger shows a run entry in the detail pane", async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-1",
        thread_id: "thread-1",
        title: "Triggerable task",
        prompt: "Summarize thread",
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-07-02T01:00:00+00:00",
        last_run_at: null,
        last_run_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-07-01T00:00:00+00:00",
        updated_at: "2026-07-01T00:00:00+00:00",
      },
    ],
  });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByRole("button", { name: "Trigger now" }).click();
  await expect(page.getByTestId("scheduled-task-runs")).toContainText("1 run");
  await expect(
    page.getByTestId("scheduled-task-run-list").getByText(/Manual · Success/i),
  ).toBeVisible();
});

test("detail pane falls back to a visible task after filters hide the selected task", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-enabled",
        thread_id: "thread-1",
        title: "Enabled task",
        prompt: "Enabled prompt",
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-07-02T01:00:00+00:00",
        last_run_at: null,
        last_run_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-07-01T00:00:00+00:00",
        updated_at: "2026-07-01T00:00:00+00:00",
      },
      {
        id: "task-paused",
        thread_id: "thread-2",
        title: "Paused task",
        prompt: "Paused prompt",
        schedule_type: "cron",
        schedule_spec: { cron: "0 10 * * *" },
        timezone: "UTC",
        status: "paused",
        next_run_at: "2026-07-02T02:00:00+00:00",
        last_run_at: null,
        last_run_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-07-01T00:00:00+00:00",
        updated_at: "2026-07-01T00:00:00+00:00",
      },
    ],
  });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-item-task-paused").click();
  await expect(
    page.getByTestId("scheduled-task-detail").getByText("Paused task"),
  ).toBeVisible();

  await page.getByRole("button", { name: "Enabled", exact: true }).click();

  await expect(
    page.getByTestId("scheduled-task-detail").getByText("Enabled task"),
  ).toBeVisible();
  await expect(
    page.getByTestId("scheduled-task-item-task-enabled"),
  ).toBeVisible();
  await expect(page.getByTestId("scheduled-task-item-task-paused")).toHaveCount(
    0,
  );
});
