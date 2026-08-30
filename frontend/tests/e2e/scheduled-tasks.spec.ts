import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe.configure({ mode: "serial" });

const TASK = {
  id: "task-1",
  thread_id: "thread-1",
  context_mode: "fresh_thread_per_run" as const,
  last_thread_id: null,
  title: "Daily summary",
  prompt: "Summarize thread",
  schedule_type: "cron" as const,
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "UTC",
  status: "enabled" as const,
  next_run_at: "2026-07-02T01:00:00+00:00",
  last_run_at: null,
  last_run_id: null,
  last_error: null,
  run_count: 0,
  created_at: "2026-07-01T00:00:00+00:00",
  updated_at: "2026-07-01T00:00:00+00:00",
};

test("scheduled tasks page is reachable from sidebar", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [TASK] });

  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: /scheduled tasks/i }).click();
  await page.waitForURL("**/workspace/scheduled-tasks");
  await expect(page).toHaveURL(/workspace\/scheduled-tasks/);
  await expect(
    page.getByRole("button", { name: /Daily summary/i }),
  ).toBeVisible();

  await page.getByTestId("scheduled-task-item-task-1").click();
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
      { ...TASK, thread_id: MOCK_THREAD_ID, title: "Thread task" },
    ],
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  // The header link carries the thread_id filter (unlike the sidebar link),
  // so target it via its aria-label to avoid a strict-mode ambiguity.
  await page.getByLabel("Scheduled tasks", { exact: true }).click();
  await page.waitForURL(new RegExp(`thread_id=${MOCK_THREAD_ID}`));
});

test("user can create a scheduled task from the create page", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [] });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-create-toggle").click();
  await page.waitForURL("**/workspace/scheduled-tasks/new");
  await expect(page).toHaveURL(/workspace\/scheduled-tasks\/new/);

  await page.getByPlaceholder("Task title").fill("Created from UI");
  await page.getByPlaceholder("Prompt").fill("Summarize thread");
  await page.getByRole("button", { name: "Create", exact: true }).click();

  await expect(
    page.getByRole("button", { name: /Created from UI/i }),
  ).toBeVisible();
});

test("creating a task from a thread filter returns to the filtered list", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [] });

  await page.goto("/workspace/scheduled-tasks?thread_id=thread-from-link");
  await page.getByTestId("scheduled-task-create-toggle").click();
  await page.waitForURL(
    "**/workspace/scheduled-tasks/new?thread_id=thread-from-link",
  );

  await expect(page.getByPlaceholder("Thread ID")).toHaveValue(
    "thread-from-link",
  );
  await page.getByPlaceholder("Task title").fill("Filtered create");
  await page.getByPlaceholder("Prompt").fill("Keep thread filter");
  await page.getByRole("button", { name: "Create", exact: true }).click();

  await page.waitForURL(
    "**/workspace/scheduled-tasks?thread_id=thread-from-link",
  );
  await expect(
    page.getByRole("button", { name: /Filtered create/i }),
  ).toBeVisible();
});

test("creating a fresh task from a thread filter returns to the global list", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [] });

  await page.goto("/workspace/scheduled-tasks?thread_id=thread-from-link");
  await page.getByTestId("scheduled-task-create-toggle").click();
  await page.waitForURL(
    "**/workspace/scheduled-tasks/new?thread_id=thread-from-link",
  );

  await page.getByRole("button", { name: "Fresh thread" }).click();
  await page.getByPlaceholder("Task title").fill("Fresh from filter");
  await page.getByPlaceholder("Prompt").fill("No thread filter");
  await page.getByRole("button", { name: "Create", exact: true }).click();

  await page.waitForURL((url) => {
    return (
      url.pathname.endsWith("/workspace/scheduled-tasks") &&
      !url.searchParams.has("thread_id")
    );
  });
  await expect(
    page.getByRole("button", { name: /Fresh from filter/i }),
  ).toBeVisible();
});

test("creating a reuse-thread task follows the submitted thread id", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [] });

  await page.goto("/workspace/scheduled-tasks?thread_id=thread-from-link");
  await page.getByTestId("scheduled-task-create-toggle").click();
  await page.waitForURL(
    "**/workspace/scheduled-tasks/new?thread_id=thread-from-link",
  );

  await page.getByPlaceholder("Thread ID").fill("thread-other");
  await page.getByPlaceholder("Task title").fill("Reuse other thread");
  await page.getByPlaceholder("Prompt").fill("Different target");
  await page.getByRole("button", { name: "Create", exact: true }).click();

  await page.waitForURL("**/workspace/scheduled-tasks?thread_id=thread-other");
  await expect(
    page.getByRole("button", { name: /Reuse other thread/i }),
  ).toBeVisible();
});

test("user can create a one-time scheduled task from the create page", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [] });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-create-toggle").click();
  await page.waitForURL("**/workspace/scheduled-tasks/new");

  await page.getByPlaceholder("Task title").fill("One-time from UI");
  await page.getByPlaceholder("Prompt").fill("Run once");
  await page.getByRole("button", { name: "One-time", exact: true }).click();

  await expect(page.getByText("Enter a valid date and time")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create", exact: true }),
  ).toBeDisabled();

  await page.getByLabel("Year").fill("2027");
  await page.getByLabel("Month").fill("8");
  await page.getByLabel("Day").fill("15");
  await page.getByLabel("Time").fill("09:30");

  await expect(page.getByText("Enter a valid date and time")).toHaveCount(0);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  await expect(
    page.getByRole("button", { name: /One-time from UI/i }),
  ).toBeVisible();
});

test("duplicate fills the create form without creating a task", async ({
  page,
}) => {
  let createRequests = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname.endsWith("/api/scheduled-tasks")
    ) {
      createRequests += 1;
    }
  });
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-copy-source",
        thread_id: "thread-copy-source",
        context_mode: "reuse_thread",
        title: "Daily summary",
        prompt: "Summarize this conversation",
        schedule_type: "cron",
        schedule_spec: { cron: "0 18 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-08-28T18:00:00Z",
        last_run_at: null,
        last_run_id: null,
        last_thread_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: "2026-08-01T00:00:00Z",
      },
    ],
  });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-item-task-copy-source").click();
  await page
    .getByTestId("scheduled-task-detail")
    .getByRole("button", { name: "Duplicate" })
    .click();
  await page.waitForURL("**/workspace/scheduled-tasks/new**");
  await expect(page).toHaveURL(/[?&]from=task-copy-source/);
  expect(new URL(page.url()).searchParams.has("prompt")).toBe(false);

  const createForm = page.getByTestId("scheduled-task-create-form");
  await expect(createForm.getByPlaceholder("Task title")).toHaveValue(
    "Daily summary (Copy)",
  );
  await expect(createForm.getByPlaceholder("Prompt")).toHaveValue(
    "Summarize this conversation",
  );
  await expect(createForm.getByPlaceholder("Thread ID")).toHaveValue(
    "thread-copy-source",
  );
  await expect(createForm.getByTestId("schedule-preview")).toHaveText(
    "Every day at 18:00 (UTC)",
  );
  await expect(createForm.getByPlaceholder("Task title")).toBeFocused();
  expect(createRequests).toBe(0);
});

test("duplicating a fresh-thread task keeps isolated runs", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-fresh-copy",
        thread_id: "thread-last-run",
        context_mode: "fresh_thread_per_run",
        title: "Nightly digest",
        prompt: "Write a digest",
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-08-28T09:00:00Z",
        last_run_at: null,
        last_run_id: null,
        last_thread_id: "thread-last-run",
        last_error: null,
        run_count: 1,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: "2026-08-01T00:00:00Z",
      },
    ],
  });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-item-task-fresh-copy").click();
  await page
    .getByTestId("scheduled-task-detail")
    .getByRole("button", { name: "Duplicate" })
    .click();
  await page.waitForURL("**/workspace/scheduled-tasks/new**");

  const createForm = page.getByTestId("scheduled-task-create-form");
  await expect(createForm.getByPlaceholder("Task title")).toHaveValue(
    "Nightly digest (Copy)",
  );
  await expect(createForm.getByPlaceholder("Prompt")).toHaveValue(
    "Write a digest",
  );
  await expect(
    createForm.getByRole("button", { name: "Fresh thread" }),
  ).toHaveAttribute("data-variant", "default");
  await expect(createForm.getByPlaceholder("Thread ID")).toHaveCount(0);
});

test("reuse-thread tasks explain their context and busy-thread queue behavior", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-reuse",
        thread_id: "thread-1",
        context_mode: "reuse_thread",
        title: "Conversation summary",
        prompt: "Summarize this conversation",
        schedule_type: "cron",
        schedule_spec: { cron: "0 18 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-07-02T18:00:00+00:00",
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
  await page.getByTestId("scheduled-task-item-task-reuse").click();

  const detailNotice = page
    .getByTestId("scheduled-task-detail")
    .getByRole("alert");
  await expect(detailNotice).toContainText(
    "Uses this thread's conversation history",
  );
  await expect(detailNotice).toContainText(
    "queues this occurrence and starts it when the thread is available",
  );

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByTestId("scheduled-task-create-toggle").click();
  await page.waitForURL("**/workspace/scheduled-tasks/new");

  const createForm = page.getByTestId("scheduled-task-create-form");
  await expect(createForm.getByRole("alert")).toHaveCount(0);
  await createForm.getByRole("button", { name: "Reuse thread" }).click();

  const createNotice = createForm.getByRole("alert");
  await expect(createNotice).toContainText(
    "Uses this thread's conversation history",
  );
  await expect(createNotice).toContainText(
    "It fails if the configured queue wait limit is exceeded",
  );

  await createForm.getByRole("button", { name: "Fresh thread" }).click();
  await expect(createForm.getByRole("alert")).toHaveCount(0);
});

test("user can pause a scheduled task from the detail dialog", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [TASK] });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-item-task-1").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("dialog").getByText("Daily summary"),
  ).toBeVisible();

  await page.getByRole("button", { name: "Pause" }).click();
  await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
});

test("trigger shows a run entry in the detail dialog", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [TASK] });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-item-task-1").click();
  await page.getByRole("button", { name: "Trigger now" }).click();

  await expect(page.getByTestId("scheduled-task-runs")).toContainText("1 run");
  await expect(
    page.getByTestId("scheduled-task-run-list").getByText(/Manual · Success/i),
  ).toBeVisible();
});

test("filtering hides tasks and closes the detail dialog", async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      { ...TASK, id: "task-enabled", title: "Enabled task", status: "enabled" },
      {
        ...TASK,
        id: "task-paused",
        thread_id: "thread-2",
        title: "Paused task",
        status: "paused",
        schedule_spec: { cron: "0 10 * * *" },
      },
    ],
  });

  await page.goto("/workspace/scheduled-tasks");
  await page.getByTestId("scheduled-task-item-task-paused").click();
  await expect(page.getByRole("dialog").getByText("Paused task")).toBeVisible();

  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Enabled", exact: true }).click();

  await expect(page.getByTestId("scheduled-task-item-task-paused")).toHaveCount(
    0,
  );
  await expect(
    page.getByTestId("scheduled-task-item-task-enabled"),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
