import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test("hides background tasks and sends no task request when the feature is unavailable", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Background work" }],
    features: { mcpTasksEnabled: false },
  });

  let taskRequests = 0;
  await page.route(`**/api/threads/${MOCK_THREAD_ID}/mcp-tasks*`, (route) => {
    taskRequests += 1;
    return route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "MCP task service is unavailable" }),
    });
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await expect(page.getByTestId("background-tasks-trigger")).toHaveCount(0);
  await page.waitForTimeout(500);
  expect(taskRequests).toBe(0);
});

test("shows, refreshes, and cancels current-chat background tasks", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Background work" }],
  });

  let getCalls = 0;
  let exportDetailCalls = 0;
  let reportCancelRequested = false;
  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/mcp-tasks/*/cancel`,
    (route) => {
      reportCancelRequested = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "task-report",
          task_name: "Generate quarterly report",
          status: "working",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:02:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: true,
        }),
      });
    },
  );

  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/mcp-tasks/task-export`,
    (route) => {
      exportDetailCalls += 1;
      const notificationStopped = exportDetailCalls > 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "task-export",
          task_name: "Export archive",
          status: "failed",
          created_at: "2026-08-07T23:00:00+00:00",
          updated_at: "2026-08-07T23:01:00+00:00",
          error: "Archive service unavailable",
          tracking_degraded: false,
          cancel_requested: false,
          result: null,
          result_preview: "Partial export details",
          result_truncated: true,
          result_artifact: { path: "/mnt/user-data/outputs/export.zip" },
          input_required: null,
          last_poll_error: "Remote worker disconnected",
          last_polled_at: "2026-08-07T23:01:00+00:00",
          notification_status: notificationStopped ? "dead_letter" : "retry",
          notification_error: notificationStopped
            ? "Notification delivery stopped after 5 failed attempts"
            : "Agent notification failed",
          notification_attempt_count: notificationStopped ? 5 : 2,
        }),
      });
    },
  );

  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/mcp-tasks/task-review`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "task-review",
          task_name: "Review budget",
          status: "input_required",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:01:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: false,
          result: null,
          result_preview: null,
          result_truncated: false,
          result_artifact: null,
          input_required: { prompt: "Approve the revised budget?" },
          last_poll_error: null,
          last_polled_at: "2026-08-08T00:01:00+00:00",
        }),
      }),
  );

  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/mcp-tasks/task-stuck`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "task-stuck",
          task_name: "Cancel remote export",
          status: "submitted",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:03:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: true,
          result: null,
          result_preview: null,
          result_truncated: false,
          result_artifact: null,
          input_required: null,
          last_poll_error: null,
          last_polled_at: "2026-08-08T00:01:00+00:00",
          last_cancel_error: "Remote cancellation timed out",
          cancel_attempt_count: 4,
        }),
      }),
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
          status: "working",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:01:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: reportCancelRequested,
          remote_task_id: "must-not-be-rendered",
        },
        {
          task_id: "task-review",
          task_name: "Review budget",
          status: "input_required",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:01:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: false,
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
        {
          task_id: "task-stuck",
          task_name: "Cancel remote export",
          status: "submitted",
          created_at: "2026-08-08T00:00:00+00:00",
          updated_at: "2026-08-08T00:03:00+00:00",
          error: null,
          tracking_degraded: false,
          cancel_requested: true,
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

  await page
    .getByTestId("background-task-task-export")
    .getByRole("button", { name: "View details" })
    .click();
  await expect(page.getByText("Partial export details")).toBeVisible();
  await expect(page.getByText("Remote worker disconnected")).toBeVisible();
  await expect(page.getByText("Agent notification failed")).toBeVisible();
  await expect(
    page.getByText(
      "Chat notification attempt 2 failed; DeerFlow will retry with backoff.",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("/mnt/user-data/outputs/export.zip"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Chat notification delivery stopped after repeated or permanent failures.",
    ),
  ).toBeVisible({ timeout: 7_000 });
  await expect(
    page.getByText("Notification delivery stopped after 5 failed attempts"),
  ).toBeVisible();
  expect(exportDetailCalls).toBeGreaterThan(1);

  await page
    .getByTestId("background-task-task-review")
    .getByRole("button", { name: "View details" })
    .click();
  await expect(page.getByText("Approve the revised budget?")).toBeVisible();
  await expect(
    page.getByText(
      "This integration cannot send your response back to the remote task yet.",
    ),
  ).toBeVisible();

  await page
    .getByTestId("background-task-task-stuck")
    .getByRole("button", { name: "View details" })
    .click();
  await expect(page.getByText("Remote cancellation timed out")).toBeVisible();
  await expect(
    page.getByText(
      "Cancellation attempt 4 failed; DeerFlow will keep retrying.",
    ),
  ).toBeVisible();

  await expect.poll(() => getCalls, { timeout: 5_000 }).toBeGreaterThan(1);

  await page
    .getByTestId("background-task-task-report")
    .getByRole("button", { name: "Cancel task" })
    .click();
  await expect(
    page
      .getByTestId("background-task-task-report")
      .getByRole("button", { name: "Cancelling…" }),
  ).toBeDisabled();
  await expect(
    page.getByTestId("background-task-task-report").getByRole("button", {
      name: "Cancel task",
    }),
  ).toHaveCount(0);
});
