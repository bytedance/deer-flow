import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test("shows, refreshes, and cancels current-chat background tasks", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Background work" }],
  });

  let getCalls = 0;
  let reportCancelled = false;
  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/mcp-tasks/*/cancel`,
    (route) => {
      reportCancelled = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "task-report",
          task_name: "Generate quarterly report",
          status: "cancelled",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:02:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: true,
        }),
      });
    },
  );

  await page.route(`**/api/threads/${MOCK_THREAD_ID}/mcp-tasks*`, (route) => {
    getCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          task_id: "task-report",
          task_name: "Generate quarterly report",
          status: reportCancelled ? "cancelled" : "working",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:01:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: reportCancelled,
          remote_task_id: "must-not-be-rendered",
        },
        {
          task_id: "task-export",
          task_name: "Export archive",
          status: "failed",
          created_at: "2026-08-07T23:00:00+00:00",
          updated_at: "2026-08-07T23:01:00+00:00",
          error: "Archive service unavailable",
          tracking_degraded: false,
          cancel_requested: false,
        },
      ]),
    });
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  const trigger = page.getByTestId("background-tasks-trigger");
  await expect(trigger).toBeVisible({ timeout: 15_000 });
  await trigger.click();

  await expect(
    page.getByRole("heading", { name: "Background tasks" }),
  ).toBeVisible();
  await expect(page.getByText("Generate quarterly report")).toBeVisible();
  await expect(page.getByText("Export archive")).toBeVisible();
  await expect(page.getByText("Archive service unavailable")).toBeVisible();
  await expect(page.getByText("must-not-be-rendered")).toHaveCount(0);

  await expect.poll(() => getCalls, { timeout: 5_000 }).toBeGreaterThan(1);

  await page.getByRole("button", { name: "Cancel task" }).click();
  await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
  await expect(
    page.getByTestId("background-task-task-report").getByRole("button", {
      name: "Cancel task",
    }),
  ).toHaveCount(0);
});
