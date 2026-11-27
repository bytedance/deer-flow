import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// The viewer's zone differs from the task's, so a result that leans on either
// UTC or the browser zone shows up as a wrong time.
test.use({ timezoneId: "Asia/Shanghai" });

for (const { runAt, time, nextRunAt } of [
  { runAt: "2027-12-07", time: "00:00", nextRunAt: "2027-12-07T05:00:00Z" },
  {
    runAt: "2027-12-07T09:00.5",
    time: "09:00",
    nextRunAt: "2027-12-07T14:00:00.500Z",
  },
  {
    runAt: "2027-12-07T09:00,5",
    time: "09:00",
    nextRunAt: "2027-12-07T14:00:00.500Z",
  },
]) {
  test(`stored run_at ${runAt} shows and edits in the task's zone`, async ({
    page,
  }) => {
    const patches: Record<string, unknown>[] = [];
    page.on("request", (request) => {
      if (
        request.method() === "PATCH" &&
        new URL(request.url()).pathname.includes("/api/scheduled-tasks")
      ) {
        patches.push(request.postDataJSON() as Record<string, unknown>);
      }
    });
    mockLangGraphAPI(page, {
      threads: [],
      scheduledTasks: [
        {
          id: "date-only-task",
          thread_id: null,
          title: "Date-only task",
          prompt: "Summarize",
          schedule_type: "once",
          // Preserve the chat/API format while showing its task-zone wall time.
          schedule_spec: { run_at: runAt },
          timezone: "America/New_York",
          status: "enabled",
          next_run_at: nextRunAt,
          last_run_at: null,
          last_run_id: null,
          last_error: null,
          run_count: 0,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:00:00Z",
        },
      ],
    });

    // The schedule line drops the year inside the current year and turns
    // relative ("Tomorrow") in the final week, so pin "now" well before the run.
    await page.clock.setFixedTime(new Date("2026-10-01T00:00:00Z"));
    await page.goto("/workspace/scheduled-tasks");
    const detail = page.getByTestId("scheduled-task-detail");
    // The schedule line itself, read from run_at. The separate next-run line
    // comes from the server's next_run_at and was right even before.
    await expect(
      detail.getByText(`Once, Dec 7, 2027 ${time} (America/New_York)`, {
        exact: true,
      }),
    ).toBeVisible();

    await detail.getByRole("button", { name: "Edit", exact: true }).click();
    const form = page.getByTestId("scheduled-task-form");
    await expect(form.getByLabel("Run at")).toHaveValue(`2027-12-07T${time}`);

    await form.getByLabel("Title", { exact: true }).fill("Renamed task");
    await form
      .getByRole("button", { name: "Save changes", exact: true })
      .click();
    await expect.poll(() => patches.length).toBe(1);
    // Only the title changed, so the stored run_at is not rewritten.
    expect(patches[0]).not.toHaveProperty("schedule_spec");
  });
}
