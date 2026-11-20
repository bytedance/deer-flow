import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const width of [1280, 375]) {
  for (const cron of ["30 14 * * 1,3,5", "30 14 21 * *"]) {
    test(`custom cron preserves ${cron} through saving at width ${width}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      const patches: Record<string, unknown>[] = [];
      page.on("request", (request) => {
        if (
          request.method() === "PATCH" &&
          new URL(request.url()).pathname === "/api/scheduled-tasks/cron-task"
        ) {
          patches.push(request.postDataJSON() as Record<string, unknown>);
        }
      });
      mockLangGraphAPI(page, {
        threads: [],
        scheduledTasks: [
          {
            id: "cron-task",
            thread_id: null,
            title: "Scheduled report",
            prompt: "Prepare the report",
            schedule_type: "cron",
            schedule_spec: { cron },
            timezone: "UTC",
            status: "enabled",
            next_run_at: "2099-01-21T14:30:00Z",
            last_run_at: null,
            last_run_id: null,
            last_error: null,
            run_count: 0,
            created_at: "2026-10-01T00:00:00Z",
            updated_at: "2026-10-01T00:00:00Z",
          },
        ],
      });

      await page.goto("/workspace/scheduled-tasks");
      await page
        .getByTestId("scheduled-task-detail")
        .getByRole("button", { name: "Edit", exact: true })
        .click();
      const form = page.getByTestId("scheduled-task-form");
      await form.getByTestId("schedule-preset").click();
      await page.getByRole("option", { name: "Custom cron" }).click();
      await expect(form.getByLabel("Cron expression")).toHaveValue(cron);

      await form.getByLabel("Title", { exact: true }).fill("Renamed report");
      await form.getByRole("button", { name: "Save changes" }).click();

      await expect.poll(() => patches.length).toBe(1);
      expect(patches[0]).toEqual({ title: "Renamed report" });
      await expect(form).toHaveCount(0);
    });
  }
}
