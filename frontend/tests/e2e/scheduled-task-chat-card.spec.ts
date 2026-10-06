import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, type MockScheduledTask } from "./utils/mock-api";
import { expectNoRawIdentifiers } from "./utils/readable";
import {
  conversation,
  scheduledTake,
  setLocaleCookie,
  type ScheduledTake,
} from "./utils/scheduled-fixtures";

test.describe.configure({ mode: "serial" });

const COPY = {
  en: {
    stops: "every item on the checklist is checked, pauses itself",
    runNow: "Run once now",
    trialStarted: "Trial run started",
    openChat: "Open chat",
    openTask: "Open task",
    active: "Active",
    pausedByAgent: "Paused by agent",
    footer: "Trial runs don't count toward the cap.",
  },
  zh: {
    stops: "清单上的所有项都已勾选，满足后自动暂停",
    runNow: "立即试运行",
    trialStarted: "试运行已开始",
    openChat: "打开对话",
    openTask: "查看任务",
    active: "已启用",
    pausedByAgent: "已由智能体暂停",
    footer: "试运行不计入上限。",
  },
} as const;

/** The recorded task as it was right after creation: active, nothing run yet. */
function freshTask(take: ScheduledTake): MockScheduledTask {
  return {
    ...take.task,
    status: "enabled",
    next_run_at: "2099-10-05T12:20:36+00:00",
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    run_count: 0,
    automatic_runs_used: 0,
    active_run_status: null,
  };
}

async function openChat(page: Page, take: ScheduledTake) {
  await setLocaleCookie(page, take.lang);
  mockLangGraphAPI(page, {
    threads: [take.chatThread],
    scheduledTasks: [freshTask(take)],
  });
  await page.goto(`/workspace/chats/${take.chatThread.thread_id}`);
}

const cards = (page: Page) => page.getByTestId("scheduled-task-card");

for (const name of ["en-3", "zh-1"] as const) {
  const take = scheduledTake(name);
  const copy = COPY[take.lang];

  test(`${name}: the schedule result renders as a live card and the reply stays readable`, async ({
    page,
  }) => {
    await openChat(page, take);
    // One card per turn: the create result and the trial result.
    await expect(cards(page)).toHaveCount(2);
    const card = cards(page).first();
    await expect(card).toContainText(take.task.title);
    await expect(card).toContainText(copy.stops);
    await expect(card.getByTestId("scheduled-task-card-status")).toHaveText(
      copy.active,
    );
    await expect(page.getByText(copy.footer).first()).toBeVisible();
    await expectNoRawIdentifiers(card);
    await expectNoRawIdentifiers(conversation(page));
  });

  test(`${name}: Run once now triggers once and links the trial chat`, async ({
    page,
  }) => {
    const triggers: string[] = [];
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        request.url().endsWith(`/api/scheduled-tasks/${take.task.id}/trigger`)
      ) {
        triggers.push(request.url());
      }
    });
    await openChat(page, take);
    const card = cards(page).last();
    await card.getByRole("button", { name: copy.runNow }).dblclick();
    await expect(card.getByTestId("scheduled-task-card-trial")).toContainText(
      copy.trialStarted,
    );
    expect(triggers).toHaveLength(1);
    await expect(
      card.getByRole("link", { name: copy.openChat }),
    ).toHaveAttribute("href", `/workspace/chats/trial-thread-${take.task.id}`);
  });

  test(`${name}: Open task selects the task on the tasks page`, async ({
    page,
  }) => {
    await openChat(page, take);
    await cards(page)
      .first()
      .getByRole("link", { name: copy.openTask })
      .click();
    await page.waitForURL(
      `**/workspace/scheduled-tasks?task_id=${take.task.id}`,
    );
    await expect(page.getByTestId("scheduled-task-detail")).toHaveAttribute(
      "data-task-id",
      take.task.id,
    );
  });

  test(`${name}: the card follows the task to Paused by agent without a reload`, async ({
    page,
  }) => {
    await page.clock.install();
    await openChat(page, take);
    const card = cards(page).last();
    await expect(card.getByTestId("scheduled-task-card-status")).toHaveText(
      copy.active,
    );
    // The recorded final state: run 2 asked the schedule to stop.
    await page.route(`**/api/scheduled-tasks/${take.task.id}`, (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: take.task })
        : route.fallback(),
    );
    await page.clock.fastForward(16_000);
    await expect(card.getByTestId("scheduled-task-card-status")).toHaveText(
      copy.pausedByAgent,
    );
    await expect(
      cards(page).first().getByTestId("scheduled-task-card-status"),
    ).toHaveText(copy.pausedByAgent);
    await expectNoRawIdentifiers(card);
  });
}
