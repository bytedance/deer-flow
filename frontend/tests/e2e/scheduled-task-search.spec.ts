import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const common = {
  thread_id: "scope-thread",
  timezone: "UTC",
  next_run_at: "2027-01-01T09:00:00Z",
  last_run_at: null,
  last_run_id: null,
  last_error: null,
  run_count: 0,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};
const tasks = [
  {
    ...common,
    id: "report",
    title: "Weekly REPORT",
    prompt: "Summarize revenue",
    schedule_type: "cron" as const,
    schedule_spec: { cron: "0 9 * * *" },
    status: "enabled" as const,
  },
  {
    ...common,
    id: "digest",
    title: "Project digest",
    prompt: "汇总项目进度",
    schedule_type: "once" as const,
    schedule_spec: { run_at: "2027-01-01T09:00:00Z" },
    status: "paused" as const,
  },
  {
    ...common,
    id: "archive",
    title: "Archive report",
    prompt: "Store the report",
    schedule_type: "once" as const,
    schedule_spec: { run_at: "2027-01-01T09:00:00Z" },
    status: "paused" as const,
  },
];

test("searches titles and prompts, clears results, and hides stale detail actions", async ({
  page,
}) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (
      ["POST", "PATCH", "DELETE"].includes(request.method()) &&
      request.url().includes("/api/scheduled-tasks")
    )
      writes.push(request.url());
  });
  mockLangGraphAPI(page, { threads: [], scheduledTasks: tasks });
  await page.goto("/workspace/scheduled-tasks");
  const search = page.getByRole("searchbox", {
    name: "Search task titles or prompts",
  });
  const list = page.getByTestId("scheduled-task-list");
  const detail = page.getByTestId("scheduled-task-detail");
  await expect(list.getByRole("button")).toHaveCount(3);
  await search.fill(" REVENUE ");
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(detail).toContainText("Summarize revenue");
  await search.fill("项目进度");
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(detail).toContainText("汇总项目进度");
  await search.fill("does-not-exist");
  await expect(list.getByRole("button")).toHaveCount(0);
  await expect(page.getByTestId("scheduled-task-search-empty")).toHaveText(
    "No tasks match your search and filters.",
  );
  await expect(
    detail.getByRole("button", { name: "Edit", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Clear search", exact: true }).click();
  await expect(search).toHaveValue("");
  await expect(list.getByRole("button")).toHaveCount(3);
  expect(writes).toEqual([]);
});

test("search composes with status, type and thread scope", async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      ...tasks,
      {
        ...tasks[0]!,
        id: "outside",
        thread_id: "other-thread",
        title: "Outside report",
      },
    ],
  });
  await page.goto("/workspace/scheduled-tasks?thread_id=scope-thread");
  const list = page.getByTestId("scheduled-task-list");
  await expect(list.getByRole("button")).toHaveCount(3);
  await page
    .getByRole("searchbox", { name: "Search task titles or prompts" })
    .fill("report");
  await expect(list.getByRole("button")).toHaveCount(2);
  await page.getByRole("button", { name: "Paused", exact: true }).click();
  await expect(list.getByRole("button")).toHaveCount(1);
  await page.getByRole("button", { name: "Cron", exact: true }).click();
  await expect(list.getByRole("button")).toHaveCount(0);
  await page.getByRole("button", { name: "Clear search", exact: true }).click();
  await expect(list.getByRole("button")).toHaveCount(0);
  await page.getByRole("button", { name: "All types", exact: true }).click();
  await expect(list.getByRole("button")).toHaveCount(2);
  await expect(page.getByTestId("scheduled-task-item-outside")).toHaveCount(0);
});

test("search controls and no-match feedback are localized", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: tasks });
  await page.goto("/workspace/scheduled-tasks");
  await page.evaluate(() => {
    document.cookie = "locale=zh-CN; path=/";
  });
  await page.reload();
  await page
    .getByRole("searchbox", { name: "搜索任务标题或提示词" })
    .fill("不存在的任务");
  await expect(page.getByTestId("scheduled-task-search-empty")).toHaveText(
    "没有符合搜索内容和筛选条件的任务。",
  );
  await page.getByRole("button", { name: "清除搜索", exact: true }).click();
  await expect(
    page.getByTestId("scheduled-task-list").getByRole("button"),
  ).toHaveCount(3);
});
