import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const mode of ["create", "edit"] as const) {
  test(`${mode} blocks a nonexistent local time and submits the corrected instant`, async ({
    page,
  }) => {
    const writes: Record<string, unknown>[] = [];
    page.on("request", (request) => {
      if (
        request.method() === (mode === "create" ? "POST" : "PATCH") &&
        new URL(request.url()).pathname.includes("/api/scheduled-tasks")
      ) {
        writes.push(request.postDataJSON() as Record<string, unknown>);
      }
    });
    mockLangGraphAPI(page, {
      threads: [],
      scheduledTasks:
        mode === "create"
          ? []
          : [
              {
                id: "dst-task",
                thread_id: null,
                title: "DST task",
                prompt: "Summarize",
                schedule_type: "once",
                schedule_spec: { run_at: "2027-03-14T06:30:00Z" },
                timezone: "America/New_York",
                status: "enabled",
                next_run_at: "2027-03-14T06:30:00Z",
                last_run_at: null,
                last_run_id: null,
                last_error: null,
                run_count: 0,
                created_at: "2026-09-01T00:00:00Z",
                updated_at: "2026-09-01T00:00:00Z",
              },
            ],
    });
    await page.goto("/workspace/scheduled-tasks");
    const form = page.getByTestId(
      mode === "create"
        ? "scheduled-task-create-form"
        : "scheduled-task-detail",
    );
    if (mode === "create") {
      await form.getByRole("button", { name: "One-time" }).click();
      await form.getByPlaceholder("Task title").fill("DST task");
      await form.getByPlaceholder("Prompt").fill("Summarize");
      await form.getByTestId("schedule-timezone").click();
      await page
        .getByRole("option", { name: "America/New_York", exact: true })
        .click();
    } else {
      await form.getByRole("button", { name: "Edit", exact: true }).click();
    }
    const submit = form.getByRole("button", {
      name: mode === "create" ? "Create" : "Save edit",
      exact: true,
    });
    await form.getByLabel("Run at").fill("2027-03-14T02:30");
    await expect(form.getByRole("alert")).toContainText(
      "This local time does not exist",
    );
    await expect(submit).toBeDisabled();
    expect(writes).toHaveLength(0);
    await form.getByLabel("Run at").fill("");
    await expect(submit).toBeDisabled();
    await form.getByLabel("Run at").fill("2027-03-14T03:30");
    await expect(form.getByRole("alert")).toHaveCount(0);
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0]).toMatchObject({
      schedule_spec: { run_at: "2027-03-14T07:30:00+00:00" },
      timezone: "America/New_York",
    });
    expect(writes[0]).not.toHaveProperty("invalidRunAt");
  });
}
