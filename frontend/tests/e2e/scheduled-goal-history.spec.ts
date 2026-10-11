import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const baseTask = {
  thread_id: null,
  context_mode: "fresh_thread_per_run" as const,
  prompt: "Check the release checklist",
  schedule_type: "interval" as const,
  schedule_spec: { every_seconds: 3600 },
  timezone: "UTC",
  status: "paused" as const,
  next_run_at: null,
  last_run_at: null,
  last_run_id: null,
  last_error: null,
  run_count: 5,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};
const goalTask = {
  ...baseTask,
  id: "goal-task",
  title: "Goal task",
  goal_objective: "status.md lists every unchecked item",
  max_runs: 5,
  end_at: null,
  last_error: "stopped by the agent in run execution-stop",
};
const plainTask = {
  ...baseTask,
  id: "plain-task",
  title: "Plain task",
  last_error: "boom",
};

const run = (
  id: string,
  overrides: Record<string, unknown>,
): Record<string, unknown> => ({
  id,
  task_id: "goal-task",
  thread_id: `thread-${id}`,
  run_id: `execution-${id}`,
  scheduled_for: "2026-10-01T00:00:00Z",
  trigger: "scheduled",
  status: "success",
  error: null,
  attempt_count: 1,
  started_at: null,
  finished_at: null,
  created_at: "2026-10-01T00:00:00Z",
  ...overrides,
});
const goal = { goal_objective: goalTask.goal_objective };
const goalRuns = [
  run("met", { ...goal, goal_verdict: { satisfied: true } }),
  run("assumed", {
    ...goal,
    goal_verdict: { satisfied: true, relied_on_assumption: true },
  }),
  run("unmet", {
    ...goal,
    status: "unmet",
    error: "blocked:missing_evidence",
    goal_verdict: {
      satisfied: false,
      blocker: "missing_evidence",
      stand_down_reason: "blocked:missing_evidence",
    },
  }),
  run("stop", {
    ...goal,
    goal_verdict: { satisfied: true },
    stop_requested_run_id: "execution-stop",
  }),
  run("unchecked", { ...goal, status: "unmet", error: "evaluator_failed" }),
  run("unknown", { ...goal, status: "unmet", error: "future_reason" }),
  run("failed", { ...goal, status: "failed", error: "boom" }),
];
const plainRuns = [
  run("plain-ok", { task_id: "plain-task" }),
  run("plain-failed", {
    task_id: "plain-task",
    status: "failed",
    error: "boom",
  }),
];

async function openTask(
  page: Page,
  task: typeof goalTask | typeof plainTask,
  runs: Record<string, unknown>[],
  locale?: "zh-CN",
) {
  mockLangGraphAPI(page, { threads: [], scheduledTasks: [task] });
  await page.route(/\/api\/scheduled-tasks\/[^/]+\/runs(?:\?|$)/, (route) =>
    route.fulfill({ json: runs }),
  );
  await page.goto("/workspace/scheduled-tasks");
  if (locale) {
    await page.evaluate((value) => {
      document.cookie = `locale=${value}; path=/; SameSite=Lax`;
    }, locale);
    await page.reload();
  }
}

const rowOf = (page: Page, runId: string) =>
  page.locator(
    `[data-testid="scheduled-run-row"][data-run-id="execution-${runId}"]`,
  );

test("goal runs show their outcome; raw text stays behind Details", async ({
  page,
}) => {
  await openTask(page, goalTask, goalRuns);
  await expect(page.getByTestId("scheduled-task-goal")).toHaveText(
    "status.md lists every unchecked item",
  );
  await expect(page.getByTestId("scheduled-task-detail")).toContainText(
    "After 5 automatic runs",
  );
  await expect(page.getByTestId("scheduled-task-status")).toHaveText(
    "Paused by agent",
  );

  await expect(rowOf(page, "met").getByTestId("scheduled-run-goal")).toHaveText(
    "Goal met",
  );
  await expect(
    rowOf(page, "met").getByTestId("scheduled-run-assumption"),
  ).toHaveCount(0);
  await expect(
    rowOf(page, "assumed").getByTestId("scheduled-run-assumption"),
  ).toHaveText("Assumption made");
  const unmet = rowOf(page, "unmet");
  await expect(unmet.getByTestId("scheduled-run-goal")).toHaveText(
    "Goal not met",
  );
  await expect(unmet).toContainText("Goal check: evidence missing");
  await expect(unmet.getByTestId("scheduled-run-goal")).not.toHaveClass(
    /text-destructive/,
  );
  await expect(
    rowOf(page, "unchecked").getByTestId("scheduled-run-goal"),
  ).toHaveText("Couldn't check the goal");
  await expect(rowOf(page, "unchecked")).toContainText(
    "Couldn't check the goal; the run itself may be fine",
  );

  // An unknown goal code is not shown as text until Details is opened.
  const unknown = rowOf(page, "unknown");
  await expect(unknown.getByTestId("scheduled-run-goal")).toHaveText(
    "Goal not met",
  );
  await expect(unknown.getByText("future_reason")).toBeHidden();
  await unknown.getByText("Details").click();
  await expect(unknown.getByText("future_reason")).toBeVisible();

  await expect(
    rowOf(page, "stop").getByTestId("scheduled-run-stop-requested"),
  ).toHaveText("This run paused the task");
  await expect(page.getByTestId("scheduled-run-stop-requested")).toHaveCount(1);

  const failed = rowOf(page, "failed");
  await expect(failed).toContainText(
    "Failed while running. Open the chat to see where it stopped.",
  );
  await expect(failed.getByText("boom")).toBeHidden();
  await failed.getByText("Details").click();
  await expect(failed.getByTestId("scheduled-run-raw-error")).toHaveText(
    "boom",
  );
});

test("tasks without a goal render their runs without goal badges", async ({
  page,
}) => {
  await openTask(page, plainTask, plainRuns);
  await expect(page.getByTestId("scheduled-run-row")).toHaveCount(2);
  await expect(page.getByTestId("scheduled-task-goal")).toHaveCount(0);
  await expect(page.getByTestId("scheduled-run-goal")).toHaveCount(0);
  await expect(page.getByTestId("scheduled-run-stop-requested")).toHaveCount(0);
  await expect(page.getByTestId("scheduled-task-detail")).not.toContainText(
    "boom",
    { useInnerText: true },
  );
  const failed = rowOf(page, "plain-failed");
  await failed.getByText("Details").click();
  await expect(failed.getByTestId("scheduled-run-raw-error")).toHaveText(
    "boom",
  );
});

test("goal outcomes use the Chinese copy", async ({ page }) => {
  await openTask(page, goalTask, goalRuns, "zh-CN");
  await expect(page.getByTestId("scheduled-task-detail")).toContainText(
    "每次运行的目标",
  );
  await expect(rowOf(page, "met").getByTestId("scheduled-run-goal")).toHaveText(
    "目标已达成",
  );
  await expect(
    rowOf(page, "assumed").getByTestId("scheduled-run-assumption"),
  ).toHaveText("含假设");
  await expect(
    rowOf(page, "unchecked").getByTestId("scheduled-run-goal"),
  ).toHaveText("未能检查目标");
  await expect(page.getByTestId("scheduled-task-status")).toHaveText(
    "已由智能体暂停",
  );
  await expect(rowOf(page, "unmet")).toContainText("目标检查：缺少依据");
  await expect(rowOf(page, "failed")).toContainText("运行中出错");
});
