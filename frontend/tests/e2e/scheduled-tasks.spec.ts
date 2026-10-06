import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import {
  MOCK_THREAD_ID,
  mockLangGraphAPI,
  type MockAPIOptions,
  type MockScheduledTask,
  type MockScheduledTaskRun,
} from "./utils/mock-api";
import { expectNoRawIdentifiers } from "./utils/readable";

test.describe.configure({ mode: "serial" });

function task(overrides: Partial<MockScheduledTask> = {}): MockScheduledTask {
  return {
    id: "task-1",
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    title: "Daily summary",
    prompt: "Summarize thread",
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
    status: "enabled",
    next_run_at: "2027-07-02T09:00:00+00:00",
    last_run_at: null,
    last_run_id: null,
    last_error: null,
    run_count: 0,
    created_at: "2026-07-01T00:00:00+00:00",
    updated_at: "2026-07-01T00:00:00+00:00",
    ...overrides,
  };
}

// Recorded takes (ux-audit evidence en-3 / zh-1) with the new response fields.
function fixture<T>(name: string): T {
  return JSON.parse(
    readFileSync(
      new URL(`./fixtures/scheduled/${name}`, import.meta.url),
      "utf8",
    ),
  ) as T;
}
const en3 = fixture<MockScheduledTask>("en-3-task.json");
const en3History = fixture<MockScheduledTaskRun[]>("en-3-runs.json");
const zh1 = fixture<MockScheduledTask>("zh-1-task.json");
const zh1History = fixture<MockScheduledTaskRun[]>("zh-1-runs.json");

async function useChinese(page: Page) {
  await page
    .context()
    .addCookies([
      { name: "locale", value: "zh-CN", url: "http://localhost:3000" },
    ]);
}

function writesTo(page: Page, method: string, pathname: string) {
  const bodies: Record<string, unknown>[] = [];
  page.on("request", (request) => {
    if (
      request.method() === method &&
      new URL(request.url()).pathname === pathname
    ) {
      let body: Record<string, unknown> | null = null;
      try {
        body = request.postDataJSON() as Record<string, unknown> | null;
      } catch {
        body = null;
      }
      bodies.push(body ?? {});
    }
  });
  return bodies;
}

async function openPage(page: Page, options: MockAPIOptions, query = "") {
  mockLangGraphAPI(page, { threads: [], ...options });
  await page.goto(`/workspace/scheduled-tasks${query}`);
}

const detail = (page: Page) => page.getByTestId("scheduled-task-detail");
const form = (page: Page) => page.getByTestId("scheduled-task-form");

test("scheduled tasks page is reachable from sidebar", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [task()] });

  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: /scheduled tasks/i }).click();
  await page.waitForURL("**/workspace/scheduled-tasks");
  await expect(
    page.getByRole("button", { name: /Daily summary/i }),
  ).toBeVisible();
  await expect(page.getByTestId("scheduled-task-runs")).toContainText("0 runs");
});

test("thread page opens the chat's tasks and Show all clears the filter", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Thread with schedules",
        updated_at: "2025-06-01T12:00:00Z",
      },
    ],
    scheduledTasks: [
      task({
        id: "task-1",
        title: "Thread task",
        origin_thread_id: MOCK_THREAD_ID,
      }),
      task({ id: "task-2", title: "Other task" }),
    ],
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await page
    .locator("header")
    .getByRole("link", { name: /scheduled tasks/i })
    .click();
  await page.waitForURL(new RegExp(`thread_id=${MOCK_THREAD_ID}`));
  const chip = page.getByTestId("scheduled-task-thread-filter");
  await expect(chip).toContainText("Showing tasks from this chat");
  await expect(chip).not.toContainText(MOCK_THREAD_ID);
  const list = page.getByTestId("scheduled-task-list");
  await expect(list.getByRole("button")).toHaveCount(1);
  await chip.getByRole("button", { name: "Show all" }).click();
  await expect(page).not.toHaveURL(/thread_id=/);
  await expect(list.getByRole("button")).toHaveCount(2);
});

test("a chat without tasks of its own does not claim there are no tasks", async ({
  page,
}) => {
  await openPage(
    page,
    { scheduledTasks: [task({ id: "task-2", title: "Other task" })] },
    `?thread_id=${MOCK_THREAD_ID}`,
  );
  await expect(page.getByTestId("scheduled-task-thread-filter")).toBeVisible();
  await expect(page.getByTestId("scheduled-task-search-empty")).toBeVisible();
  await expect(page.getByTestId("scheduled-task-empty")).toHaveCount(0);
  await page
    .getByTestId("scheduled-task-thread-filter")
    .getByRole("button", { name: "Show all" })
    .click();
  await expect(
    page.getByTestId("scheduled-task-list").getByRole("button"),
  ).toHaveCount(1);
});

for (const locale of ["en-US", "zh-CN"] as const) {
  test(`empty state (${locale}) explains the feature and New task opens the dialog`, async ({
    page,
  }) => {
    const zh = locale === "zh-CN";
    if (zh) await useChinese(page);
    await openPage(page, { scheduledTasks: [] });
    const empty = page.getByTestId("scheduled-task-empty");
    await expect(empty).toContainText(
      zh ? "还没有定时任务" : "No scheduled tasks yet",
    );
    await expect(empty).toContainText(
      zh
        ? "每个工作日 9 点汇总我的 GitHub 通知"
        : "Every weekday at 9:00, summarize my GitHub notifications",
    );
    await empty
      .getByRole("button", { name: zh ? "新建任务" : "New task" })
      .click();
    await expect(
      form(page).getByRole("heading", {
        name: zh ? "新建定时任务" : "New scheduled task",
      }),
    ).toBeVisible();
    await expect(
      form(page).getByLabel(zh ? "标题" : "Title", { exact: true }),
    ).toBeFocused();
  });
}

test("New task creates a task with the default agent and selects it", async ({
  page,
}) => {
  const creates = writesTo(page, "POST", "/api/scheduled-tasks");
  await openPage(page, { scheduledTasks: [task({ id: "existing" })] });
  await page.getByTestId("scheduled-task-new").click();
  const dialog = form(page);
  await dialog.getByRole("button", { name: "Advanced" }).click();
  await expect(dialog.getByTestId("scheduled-task-form-agent")).toHaveText(
    "Default agent",
  );
  await dialog.getByRole("button", { name: "One-time" }).click();
  await dialog.getByLabel("Run at").fill("2027-07-02T09:00");
  await dialog.getByLabel("Title", { exact: true }).fill("Created from UI");
  await dialog.getByLabel("Instructions").fill("Summarize thread");
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("Task created")).toBeVisible();
  await expect(page).toHaveURL(/task_id=task-created/);
  await expect(detail(page).getByRole("heading")).toHaveText("Created from UI");
  await expect(detail(page)).not.toContainText("lead_agent");
  expect(creates).toHaveLength(1);
  expect(creates[0]).toMatchObject({
    assistant_id: "lead_agent",
    context_mode: "fresh_thread_per_run",
    title: "Created from UI",
    prompt: "Summarize thread",
    schedule_type: "once",
  });
  expect(creates[0]).not.toHaveProperty("stop_condition");
  expect(creates[0]).not.toHaveProperty("max_runs");
});

test("?task_id= selects that task and clicking another updates the URL", async ({
  page,
}) => {
  await openPage(
    page,
    {
      scheduledTasks: [
        task({ id: "first", title: "First task" }),
        task({ id: "second", title: "Second task", status: "paused" }),
        task({ id: "third", title: "Third task" }),
      ],
    },
    "?task_id=second",
  );
  await expect(detail(page).getByRole("heading")).toHaveText("Second task");
  await expect(page.getByTestId("scheduled-task-item-second")).toHaveAttribute(
    "aria-current",
    "true",
  );
  await page.getByTestId("scheduled-task-item-third").click();
  await expect(page).toHaveURL(/task_id=third/);
  await expect(detail(page).getByRole("heading")).toHaveText("Third task");
  await expect(
    page.getByTestId("scheduled-task-item-second"),
  ).not.toHaveAttribute("aria-current", "true");
});

test("the selected task's status is visible at 1280x800 without scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openPage(page, {
    scheduledTasks: [en3],
    scheduledTaskRuns: { [en3.id]: en3History },
  });
  const status = page.getByTestId("scheduled-task-status");
  await expect(status).toHaveText("Paused by agent");
  const box = await status.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(800);
});

test("at phone width the page does not scroll sideways and selecting shows the detail", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openPage(page, {
    scheduledTasks: [en3, task({ id: "weekly", title: "Weekly report" })],
    scheduledTaskRuns: { [en3.id]: en3History },
  });
  await expect(page.getByTestId("scheduled-run-row")).toHaveCount(3);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.getByTestId("scheduled-task-item-weekly").click();
  await expect(detail(page).getByRole("heading")).toHaveText("Weekly report");
  await expect(detail(page).getByRole("heading")).toBeInViewport();
});

test("paused-by-agent notice links to the run that stopped it (en-3)", async ({
  page,
}) => {
  await openPage(page, {
    scheduledTasks: [en3],
    scheduledTaskRuns: { [en3.id]: en3History },
  });
  const notice = page.getByTestId("scheduled-task-outcome");
  await expect(notice).toHaveAttribute("data-outcome", "pausedByAgent");
  await expect(notice).toContainText("Paused by agent");
  await expect(notice).toContainText("the agent found your stop condition met");
  await expect(
    notice.getByRole("link", { name: "See that run" }),
  ).toHaveAttribute(
    "href",
    "/workspace/chats/83d5133d-f8aa-4095-9bba-2aca03f8f61c",
  );
  const stops = page.getByTestId("scheduled-task-stops-when");
  await expect(stops).toContainText(
    "every item on the checklist is checked, pauses itself",
  );
  await expect(stops).toContainText("Reached");
  await expect(detail(page)).toContainText("Safety cap: 2 of 5 runs used");
  await expect(page.getByTestId(`scheduled-task-item-${en3.id}`)).toContainText(
    "Paused by agent ·",
  );
  await expect(
    detail(page).getByTestId("scheduled-task-origin-link"),
  ).toHaveAttribute(
    "href",
    "/workspace/chats/c04264b7-891e-451a-92af-8c084e1eed55",
  );
  await expect(
    detail(page).getByRole("button", { name: "Resume" }),
  ).toBeVisible();
  await expect(detail(page).getByRole("button", { name: "Pause" })).toHaveCount(
    0,
  );
});

test("auto-pause notice gives the reason and three ways forward (zh-1 variant)", async ({
  page,
}) => {
  await useChinese(page);
  const autoPaused: MockScheduledTask = {
    ...zh1,
    last_error: "paused after 3 unmet scheduled goal runs",
  };
  const runs = zh1History.map((run) =>
    run.trigger === "scheduled"
      ? {
          ...run,
          status: "unmet" as const,
          error: "blocked:missing_evidence",
          summary: null,
          stop_requested_run_id: null,
          goal_verdict: { satisfied: false, blocker: "missing_evidence" },
        }
      : run,
  );
  await openPage(page, {
    scheduledTasks: [autoPaused],
    scheduledTaskRuns: { [zh1.id]: runs },
  });
  const notice = page.getByTestId("scheduled-task-outcome");
  await expect(notice).toContainText("已暂停：连续 3 次未达成目标");
  await expect(notice).toContainText("最近一次的原因：目标检查：缺少依据");
  await expect(
    notice.getByRole("link", { name: "查看最近一次运行" }),
  ).toHaveAttribute(
    "href",
    "/workspace/chats/85e503ef-a8bf-46a3-8c4e-b697dd7f1b57",
  );
  await expect(notice.getByRole("button", { name: "仍然恢复" })).toBeVisible();
  await expect(page.getByTestId("scheduled-task-status")).toHaveText(
    "已自动暂停",
  );
  await notice.getByRole("button", { name: "修改目标" }).click();
  await expect(form(page).getByLabel("每次运行的目标（可选）")).toBeFocused();
});

test("editing goal, stop condition and cap sends only changed fields", async ({
  page,
}) => {
  const patches = writesTo(page, "PATCH", "/api/scheduled-tasks/goal-task");
  await openPage(page, {
    scheduledTasks: [
      task({
        id: "goal-task",
        title: "Checklist",
        goal_objective: "status.md lists the open items",
        stop_condition: "every item is checked",
        max_runs: 10,
        end_at: "2027-12-31T10:00:00+00:00",
      }),
    ],
  });
  await detail(page).getByRole("button", { name: "Edit" }).click();
  const dialog = form(page);
  await expect(dialog.getByLabel("Stops when (optional)")).toHaveValue(
    "every item is checked",
  );
  await dialog
    .getByLabel("Each run's goal (optional)")
    .fill("status.md lists every open item with its owner");
  await dialog
    .getByLabel("Stops when (optional)")
    .fill("every item on the checklist is checked");
  await dialog
    .getByRole("button", { name: "Clear Safety cap: number of runs" })
    .click();
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("Changes saved")).toBeVisible();
  expect(patches).toEqual([
    {
      goal_objective: "status.md lists every open item with its owner",
      stop_condition: "every item on the checklist is checked",
      max_runs: null,
    },
  ]);
  await expect(page.getByTestId("scheduled-task-stops-when")).toContainText(
    "every item on the checklist is checked, pauses itself",
  );
});

test("Resume of an exhausted task opens the renew dialog and sends the new cap", async ({
  page,
}) => {
  const resumes = writesTo(page, "POST", "/api/scheduled-tasks/limited/resume");
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      task({
        id: "limited",
        title: "Limited task",
        status: "paused",
        max_runs: 5,
        automatic_runs_used: 5,
      }),
    ],
  });
  // A plain resume (no renewal body) is refused like the backend does.
  await page.route("**/api/scheduled-tasks/limited/resume", (route) => {
    if (route.request().postData()) {
      return route.fallback();
    }
    return route.fulfill({
      status: 409,
      json: {
        detail: {
          code: "limits_exhausted",
          message: "All 5 automatic runs are used.",
          params: { limit: "max_runs", used: 5, max_runs: 5, end_at: null },
        },
      },
    });
  });
  await page.goto("/workspace/scheduled-tasks");
  await detail(page).getByRole("button", { name: "Resume" }).click();
  const dialog = page.getByRole("dialog", { name: "Extend the safety cap" });
  await expect(dialog).toContainText("5 of 5 automatic runs are used");
  await dialog.getByLabel("Safety cap: number of runs").fill("70");
  await dialog.getByRole("button", { name: "Resume" }).click();
  await expect(dialog).toHaveCount(0);
  expect(resumes.at(-1)).toEqual({ max_runs: 70 });
  await expect(page.getByText(/^Resumed/)).toBeVisible();

  // Pause again, then remove the cap instead of raising it.
  await detail(page).getByRole("button", { name: "Pause" }).click();
  await detail(page).getByRole("button", { name: "Resume" }).click();
  const again = page.getByRole("dialog", { name: "Extend the safety cap" });
  await again.getByLabel("Remove this limit").check();
  await again.getByRole("button", { name: "Resume" }).click();
  await expect(again).toHaveCount(0);
  expect(resumes.at(-1)).toEqual({ max_runs: null });
});

test("a finished task offers no Pause and explains how to extend it", async ({
  page,
}) => {
  await openPage(page, {
    scheduledTasks: [
      task({
        id: "done",
        status: "completed",
        max_runs: 3,
        automatic_runs_used: 3,
        next_run_at: null,
      }),
    ],
  });
  await expect(page.getByTestId("scheduled-task-status")).toHaveText(
    "Finished",
  );
  await expect(detail(page).getByRole("button", { name: "Pause" })).toHaveCount(
    0,
  );
  const notice = page.getByTestId("scheduled-task-outcome");
  await expect(notice).toContainText("Finished: all 3 runs used");
  await expect(
    notice.getByRole("button", { name: "Extend limit" }),
  ).toBeVisible();
  await expect(page.getByTestId("scheduled-task-item-done")).toContainText(
    "Finished · all 3 runs used",
  );
});

test("Run once now posts once even on a double click and confirms", async ({
  page,
}) => {
  const triggers = writesTo(
    page,
    "POST",
    "/api/scheduled-tasks/task-1/trigger",
  );
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [task()] });
  await page.route("**/api/scheduled-tasks/task-1/trigger", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 400));
    return route.fallback();
  });
  await page.goto("/workspace/scheduled-tasks");
  await detail(page).getByRole("button", { name: "Run once now" }).dblclick();
  await expect(page.getByText("Trial run started")).toBeVisible();
  expect(triggers).toHaveLength(1);
  const row = page.getByTestId("scheduled-run-row");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Trial run");
  await expect(row.getByRole("link", { name: "Open chat" })).toHaveAttribute(
    "href",
    "/workspace/chats/trial-thread-task-1",
  );
});

test("a recurring task mid-run reads Running now, blocks changes and polls fast", async ({
  page,
}) => {
  await page.clock.install();
  let listRequests = 0;
  page.on("request", (request) => {
    if (
      request.method() === "GET" &&
      new URL(request.url()).pathname === "/api/scheduled-tasks"
    ) {
      listRequests += 1;
    }
  });
  await openPage(page, {
    scheduledTasks: [task({ status: "enabled", active_run_status: "running" })],
  });
  await expect(page.getByTestId("scheduled-task-item-task-1")).toContainText(
    "Running now",
  );
  await expect(page.getByTestId("scheduled-task-status")).toHaveText(
    "Running now",
  );
  for (const name of ["Pause", "Edit", "Run once now"]) {
    await expect(
      detail(page).getByRole("button", { name, exact: true }),
    ).toBeDisabled();
  }
  await detail(page).getByRole("button", { name: "More actions" }).click();
  await expect(page.getByRole("menuitem", { name: "Delete" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await page.keyboard.press("Escape");
  const before = listRequests;
  await page.clock.fastForward(3500);
  await expect.poll(() => listRequests).toBeGreaterThan(before);
  const afterOne = listRequests;
  await page.clock.fastForward(3500);
  await expect.poll(() => listRequests).toBeGreaterThan(afterOne);
});

test("scheduler off: notice, and New task and Duplicate are blocked", async ({
  page,
}) => {
  await openPage(page, {
    scheduledTasks: [task()],
    features: { scheduledTasks: { running: false } },
  });
  await expect(page.getByTestId("scheduler-off-notice")).toContainText(
    "Automatic runs are off on this server",
  );
  const newTask = page.getByTestId("scheduled-task-new");
  await expect(newTask).toBeDisabled();
  await newTask.locator("..").hover();
  await expect(page.getByRole("tooltip")).toContainText(
    "New tasks can't be created while automatic runs are off.",
  );
  await detail(page).getByRole("button", { name: "More actions" }).click();
  await expect(
    page.getByRole("menuitem", { name: "Duplicate" }),
  ).toHaveAttribute("aria-disabled", "true");
  await expect(
    page.locator(
      '[role=menu] [data-disabled-reason="New tasks can\'t be created while automatic runs are off."]',
    ),
  ).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(
    detail(page).getByRole("button", { name: "Run once now" }),
  ).toBeEnabled();
});

test("Duplicate prefills the dialog, including goal and caps, without creating", async ({
  page,
}) => {
  const creates = writesTo(page, "POST", "/api/scheduled-tasks");
  await openPage(page, {
    scheduledTasks: [
      task({
        id: "source",
        title: "Research digest",
        prompt: "Summarize papers",
        assistant_id: "research-bot",
        schedule_spec: { cron: "0 18 * * *" },
        goal_objective: "digest.md lists five papers",
        stop_condition: "the reading list is empty",
        max_runs: 30,
        end_at: "2020-01-01T00:00:00+00:00",
      }),
    ],
  });
  await expect(detail(page)).toContainText("Agent: research-bot");
  await detail(page).getByRole("button", { name: "More actions" }).click();
  await page.getByRole("menuitem", { name: "Duplicate" }).click();
  const dialog = form(page);
  await expect(dialog.getByLabel("Title", { exact: true })).toHaveValue(
    "Research digest (copy)",
  );
  await expect(dialog.getByLabel("Instructions")).toHaveValue(
    "Summarize papers",
  );
  await expect(dialog.getByLabel("Each run's goal (optional)")).toHaveValue(
    "digest.md lists five papers",
  );
  await expect(dialog.getByLabel("Stops when (optional)")).toHaveValue(
    "the reading list is empty",
  );
  await expect(
    dialog.getByRole("spinbutton", { name: "Safety cap: number of runs" }),
  ).toHaveValue("30");
  // The source's end time has passed, so it is dropped with a hint.
  await expect(dialog.getByLabel(/Safety cap: end by/)).toHaveValue("");
  await expect(dialog).toContainText(
    "The original end time has passed; set a new one.",
  );
  await expect(dialog.getByTestId("schedule-preview")).toHaveText(
    "Every day at 18:00 (UTC)",
  );
  await expect(dialog.getByTestId("scheduled-task-form-agent")).toHaveText(
    "research-bot",
  );
  expect(creates).toHaveLength(0);
});

test("editing only the title keeps the one-time instant and the agent untouched", async ({
  page,
}) => {
  const patches = writesTo(page, "PATCH", "/api/scheduled-tasks/task-instant");
  await openPage(page, {
    scheduledTasks: [
      task({
        id: "task-instant",
        assistant_id: "research-bot",
        title: "Original title",
        schedule_type: "once",
        schedule_spec: { run_at: "2027-06-01T12:30:45Z" },
        timezone: "America/New_York",
        next_run_at: "2027-06-01T12:30:45Z",
      }),
    ],
  });
  await detail(page).getByRole("button", { name: "Edit" }).click();
  await form(page).getByLabel("Title", { exact: true }).fill("Renamed task");
  await form(page).getByRole("button", { name: "Save changes" }).click();
  await expect(detail(page).getByRole("heading")).toHaveText("Renamed task");
  expect(patches).toEqual([{ title: "Renamed task" }]);
});

test("reuse-thread option explains the queue behaviour in the dialog", async ({
  page,
}) => {
  await openPage(page, { scheduledTasks: [task()] });
  await page.getByTestId("scheduled-task-new").click();
  const dialog = form(page);
  await dialog.getByRole("button", { name: "Advanced" }).click();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Run in an existing chat" }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Uses this chat's history",
  );
  await expect(dialog.getByLabel("Each run's goal (optional)")).toBeDisabled();
  await dialog
    .getByRole("button", { name: "Start a new chat for each run" })
    .click();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
});

for (const locale of ["en-US", "zh-CN"] as const) {
  test(`list and detail show no raw identifiers (${locale})`, async ({
    page,
  }) => {
    const zh = locale === "zh-CN";
    if (zh) await useChinese(page);
    const source = zh ? zh1 : en3;
    const runs = zh ? zh1History : en3History;
    await openPage(page, {
      scheduledTasks: [
        source,
        task({
          id: "custom",
          title: "Custom",
          schedule_spec: { cron: "*/5 9-17 * * 1-5" },
        }),
        task({
          id: "reuse",
          title: "Reuse",
          context_mode: "reuse_thread",
          thread_id: MOCK_THREAD_ID,
        }),
      ],
      scheduledTaskRuns: { [source.id]: runs },
    });
    await expect(page.getByTestId("scheduled-run-row")).toHaveCount(3);
    await expectNoRawIdentifiers(page.getByTestId("scheduled-task-list"));
    await expectNoRawIdentifiers(detail(page));
    await page.getByTestId("scheduled-task-item-custom").click();
    await expect(detail(page).getByRole("heading")).toHaveText("Custom");
    await expectNoRawIdentifiers(detail(page));
    await page.getByTestId("scheduled-task-item-reuse").click();
    await expect(detail(page).getByRole("heading")).toHaveText("Reuse");
    await expectNoRawIdentifiers(detail(page));
  });
}
