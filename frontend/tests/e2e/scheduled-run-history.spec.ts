import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const task = {
  id: "history",
  thread_id: "thread-1",
  title: "History task",
  prompt: "Summarize",
  schedule_type: "cron" as const,
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "UTC",
  status: "enabled" as const,
  next_run_at: null,
  last_run_at: null,
  last_run_id: null,
  last_error: null,
  run_count: 101,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
const runs = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    id: `row-${i}`,
    task_id: task.id,
    thread_id: task.thread_id,
    run_id: `execution-${i}`,
    scheduled_for: "2026-01-01T00:00:00Z",
    trigger: "scheduled" as const,
    status: "success" as const,
    error: null,
    attempt_count: 1,
    started_at: null,
    finished_at: null,
    created_at: "2026-01-01T00:00:00Z",
  }));
const endpoint = /\/api\/scheduled-tasks\/history\/runs(?:\?|$)/;
async function seedRuns(
  page: Page,
  data: Record<string, ReturnType<typeof runs>>,
) {
  await page.route(/\/api\/scheduled-tasks\/[^/]+\/runs(?:\?|$)/, (route) => {
    const url = new URL(route.request().url());
    const taskId = url.pathname.split("/").at(-2)!;
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return route.fulfill({
      json: (data[taskId] ?? []).slice(
        offset,
        offset + Number(url.searchParams.get("limit") ?? 50),
      ),
    });
  });
}

for (const count of [100, 101]) {
  test(`browses ${count} runs without exposing the sentinel or an empty final page`, async ({
    page,
  }) => {
    const requests: string[] = [];
    page.on("request", (request) => {
      if (endpoint.test(request.url()))
        requests.push(new URL(request.url()).search);
    });
    mockLangGraphAPI(page, { threads: [], scheduledTasks: [task] });
    await seedRuns(page, { history: runs(count) });
    await page.goto("/workspace/scheduled-tasks");
    const list = page.getByTestId("scheduled-task-run-list");
    const older = page.getByRole("button", { name: "Older runs", exact: true });
    await expect(list.getByText(/^execution-\d+$/)).toHaveCount(50);
    await expect(list.getByText("execution-50", { exact: true })).toHaveCount(
      0,
    );
    await older.click();
    await expect(list.getByText("execution-50", { exact: true })).toBeVisible();
    await expect(list.getByText(/^execution-\d+$/)).toHaveCount(50);
    if (count === 101) {
      await older.click();
      await expect(
        list.getByText("execution-100", { exact: true }),
      ).toBeVisible();
      await expect(list.getByText(/^execution-\d+$/)).toHaveCount(1);
    }
    await expect(older).toBeDisabled();
    await page.getByRole("button", { name: "Newer runs", exact: true }).click();
    await expect(
      page.getByRole("navigation", { name: "Run history pages" }),
    ).toContainText(count === 101 ? "Page 2" : "Page 1");
    if (count === 101)
      await page
        .getByRole("button", { name: "Latest runs", exact: true })
        .click();
    await expect(list.getByText("execution-0", { exact: true })).toBeVisible();
    expect(requests).toContain("?limit=51&offset=50");
    expect(requests).not.toContain("?limit=51&offset=150");
  });
}

test("history load failure is retriable and switching tasks resets the page", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [task, { ...task, id: "other", title: "Other history" }],
  });
  await seedRuns(page, {
    history: runs(101),
    other: [
      {
        ...runs(1)[0]!,
        id: "other-row",
        task_id: "other",
        run_id: "other-execution",
      },
    ],
  });
  let fail = true;
  await page.route(endpoint, (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("offset") === "50" && fail)
      return route.fulfill({ status: 500, json: { detail: "unavailable" } });
    return route.fallback();
  });
  await page.goto("/workspace/scheduled-tasks");
  await page.getByRole("button", { name: "Older runs", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Could not load run history." }),
  ).toContainText("Could not load run history.", { timeout: 15000 });
  await expect(page.getByTestId("scheduled-task-runs")).toHaveCount(0);
  fail = false;
  await page
    .getByRole("button", { name: "Retry history", exact: true })
    .click();
  await expect(page.getByTestId("scheduled-task-run-list")).toContainText(
    "execution-50",
  );
  await page.getByTestId("scheduled-task-item-other").click();
  await expect(page.getByTestId("scheduled-task-run-list")).toContainText(
    "other-execution",
  );
  await expect(
    page.getByRole("navigation", { name: "Run history pages" }),
  ).toContainText("Page 1");
  await expect(
    page.getByRole("button", { name: "Newer runs", exact: true }),
  ).toBeDisabled();
});

test("only latest history polls and returning to latest fetches newly inserted runs", async ({
  page,
}) => {
  await page.clock.install();
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [task] });
  const rows = runs(101);
  const offsets: number[] = [];
  await page.route(endpoint, (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset") ?? 0);
    offsets.push(offset);
    return route.fulfill({
      json: rows.slice(
        offset,
        offset + Number(url.searchParams.get("limit") ?? 50),
      ),
    });
  });
  await page.goto("/workspace/scheduled-tasks");
  const list = page.getByTestId("scheduled-task-run-list");
  await expect(list).toContainText("execution-0");
  const initialRequests = offsets.length;
  await page.clock.fastForward(16000);
  await expect.poll(() => offsets.length).toBeGreaterThan(initialRequests);
  await page.getByRole("button", { name: "Older runs", exact: true }).click();
  await expect(list).toContainText("execution-50");
  const olderRequests = offsets.length;
  rows.unshift({ ...rows[0]!, id: "inserted", run_id: "new-execution" });
  await page.clock.fastForward(31000);
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(offsets.length).toBe(olderRequests);
  await expect(list).toContainText("execution-50");
  await page.getByRole("button", { name: "Latest runs", exact: true }).click();
  await expect(list).toContainText("new-execution");
  expect(offsets.at(-1)).toBe(0);
});

test("Chinese history navigation and empty results are localized", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [task] });
  await page.goto("/workspace/scheduled-tasks");
  await page.evaluate(() => {
    document.cookie = "locale=zh-CN; path=/";
  });
  await page.reload();
  const nav = page.getByRole("navigation", { name: "执行记录分页" });
  await expect(nav).toContainText("第 1 页");
  await expect(
    nav.getByRole("button", { name: "更早记录", exact: true }),
  ).toBeDisabled();
  await expect(
    nav.getByRole("button", { name: "较新记录", exact: true }),
  ).toBeDisabled();
});

test("pending history does not report an empty run count", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [task] });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(endpoint, async (route) => {
    await gate;
    await route.fulfill({ json: [] });
  });
  try {
    await page.goto("/workspace/scheduled-tasks");
    await expect(
      page.getByRole("status").filter({ hasText: "Loading runs" }),
    ).toBeVisible();
    await expect(page.getByTestId("scheduled-task-runs")).toHaveCount(0);
  } finally {
    release();
  }
  await expect(page.getByTestId("scheduled-task-runs")).toContainText("0 runs");
});
