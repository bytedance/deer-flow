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
  return page.getByTestId("scheduled-task-run-list");
}

const rowOf = (list: ReturnType<Page["getByTestId"]>, runId: string) =>
  list.locator("div.rounded-md").filter({ hasText: runId });

test("goal runs show their outcome and the unmet reason is not styled as an error", async ({
  page,
}) => {
  const list = await openTask(page, goalTask, goalRuns);
  const detail = page.getByTestId("scheduled-task-detail");
  await expect(page.getByTestId("scheduled-task-goal")).toHaveText(
    "Goal per run: status.md lists every unchecked item",
  );
  await expect(detail.getByText("Automatic runs: up to 5")).toBeVisible();
  await expect(page.getByTestId("scheduled-task-last-error")).toHaveText(
    "Last pause reason: The agent stopped its own schedule",
  );

  await expect(rowOf(list, "execution-met")).toContainText("Goal met");
  await expect(rowOf(list, "execution-assumed")).toContainText(
    "Goal met, relying on stated assumptions",
  );
  const unmet = rowOf(list, "execution-unmet").getByTestId(
    "scheduled-run-goal",
  );
  await expect(unmet).toHaveText("Goal check: evidence missing");
  await expect(unmet).toHaveAttribute("title", "blocked:missing_evidence");
  await expect(unmet).not.toHaveClass(/text-destructive/);
  await expect(
    rowOf(list, "execution-unknown").getByTestId("scheduled-run-goal"),
  ).toHaveText("future_reason");
  await expect(
    rowOf(list, "execution-stop").getByTestId("scheduled-run-stop-requested"),
  ).toHaveText("This run paused the task");
  await expect(list.getByTestId("scheduled-run-stop-requested")).toHaveCount(1);
  await expect(
    rowOf(list, "execution-failed").locator(".text-destructive"),
  ).toHaveText("boom");
});

test("tasks without a goal render their runs as before", async ({ page }) => {
  const list = await openTask(page, plainTask, plainRuns);
  await expect(list.getByText("execution-plain-ok")).toBeVisible();
  await expect(page.getByTestId("scheduled-task-goal")).toHaveCount(0);
  await expect(page.getByTestId("scheduled-task-last-error")).toHaveText(
    "Last error: boom",
  );
  await expect(list.getByTestId("scheduled-run-goal")).toHaveCount(0);
  await expect(list.getByTestId("scheduled-run-stop-requested")).toHaveCount(0);
  await expect(
    rowOf(list, "execution-plain-failed").locator(".text-destructive"),
  ).toHaveText("boom");
});

test("goal outcomes use the Chinese copy", async ({ page }) => {
  const list = await openTask(page, goalTask, goalRuns, "zh-CN");
  await expect(page.getByTestId("scheduled-task-goal")).toHaveText(
    "每次运行的目标: status.md lists every unchecked item",
  );
  await expect(rowOf(list, "execution-met")).toContainText("目标已达成");
  await expect(page.getByTestId("scheduled-task-last-error")).toHaveText(
    "上次暂停原因: 已由智能体暂停",
  );
  await expect(
    rowOf(list, "execution-unmet").getByTestId("scheduled-run-goal"),
  ).toHaveText("目标检查：缺少依据");
});
