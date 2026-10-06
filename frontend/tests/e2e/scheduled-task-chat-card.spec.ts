import { expect, test, type Page } from "@playwright/test";

import {
  mockLangGraphAPI,
  type MockScheduledTask,
  type MockThread,
} from "./utils/mock-api";
import { expectNoRawIdentifiers } from "./utils/readable";
import {
  conversation,
  liveMinuteTake,
  liveTake,
  LOCALES,
  setLocaleCookie,
} from "./utils/scheduled-fixtures";

test.describe.configure({ mode: "serial" });

// Recorded live (fixtures/scheduled/live-*.json): the conversations are
// Chinese; the UI runs in both locales over them.
const weekday = liveTake("weekday");
const minute = liveMinuteTake();

const COPY = {
  en: {
    pausesItself: ", pauses itself",
    dailyAtTen: "Every day at 10:00 (Asia/Shanghai)",
    everyMinute: "Every minute",
    runNow: "Run once now",
    trialStarted: "Trial run started",
    openChat: "Open chat",
    openTask: "Open task",
    active: "Active",
    pausedByAgent: "Paused by agent",
    reached: "✓ Reached today 16:48",
    footer: "Trial runs don't count toward the cap.",
  },
  zh: {
    pausesItself: "，满足后自动暂停",
    dailyAtTen: "每天 10:00 (Asia/Shanghai)",
    everyMinute: "每分钟",
    runNow: "立即试运行",
    trialStarted: "试运行已开始",
    openChat: "打开对话",
    openTask: "查看任务",
    active: "已启用",
    pausedByAgent: "已由智能体暂停",
    reached: "✓ 已于今天 16:48 满足",
    footer: "试运行不计入上限。",
  },
} as const;

/** The per-minute task as it was right after creation: active, nothing run yet. */
function freshMinuteTask(): MockScheduledTask {
  return {
    ...minute.task,
    status: "enabled",
    next_run_at: "2026-10-06T08:47:52+00:00",
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    run_count: 0,
    automatic_runs_used: 0,
    active_run_status: null,
  };
}

async function openChat(
  page: Page,
  lang: "en" | "zh",
  thread: MockThread,
  task: MockScheduledTask,
) {
  await setLocaleCookie(page, lang);
  mockLangGraphAPI(page, { threads: [thread], scheduledTasks: [task] });
  await page.goto(`/workspace/chats/${thread.thread_id}`);
}

const cards = (page: Page) => page.getByTestId("scheduled-task-card");

for (const lang of LOCALES) {
  const copy = COPY[lang];

  test(`${lang}: each schedule_task turn of the live chat is one live card and the replies stay readable`, async ({
    page,
  }) => {
    await openChat(page, lang, weekday.chatThread, weekday.task);
    // create, trial, edit, pause, resume: one card per turn, all one task.
    await expect(cards(page)).toHaveCount(5);
    for (const card of await cards(page).all()) {
      await expect(card).toHaveAttribute("data-task-id", weekday.task.id);
      // Every card follows the live task: resumed, daily at 10:00.
      await expect(card.getByTestId("scheduled-task-card-status")).toHaveText(
        copy.active,
      );
      await expect(card.getByTestId("scheduled-task-card-schedule")).toHaveText(
        copy.dailyAtTen,
      );
    }
    const first = cards(page).first();
    await expect(first).toContainText(weekday.task.title);
    await expect(first.getByTestId("scheduled-task-card-stops")).toContainText(
      `${weekday.task.stop_condition}${copy.pausesItself}`,
    );
    await expect(page.getByText(copy.footer).first()).toBeVisible();
    // The agent's recorded replies stay plain chat text next to the cards.
    await expect(conversation(page)).toContainText(
      "已恢复，每天早上 10 点（含周末）继续检查清单",
    );
    await expectNoRawIdentifiers(first);
    await expectNoRawIdentifiers(conversation(page));
  });

  test(`${lang}: Run once now triggers once and links the trial chat`, async ({
    page,
  }) => {
    const triggers: string[] = [];
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        request
          .url()
          .endsWith(`/api/scheduled-tasks/${weekday.task.id}/trigger`)
      ) {
        triggers.push(request.url());
      }
    });
    await openChat(page, lang, weekday.chatThread, weekday.task);
    const card = cards(page).last();
    await card.getByRole("button", { name: copy.runNow }).dblclick();
    await expect(card.getByTestId("scheduled-task-card-trial")).toContainText(
      copy.trialStarted,
    );
    expect(triggers).toHaveLength(1);
    await expect(
      card.getByRole("link", { name: copy.openChat }),
    ).toHaveAttribute(
      "href",
      `/workspace/chats/trial-thread-${weekday.task.id}`,
    );
  });

  test(`${lang}: Open task selects the task on the tasks page`, async ({
    page,
  }) => {
    await openChat(page, lang, weekday.chatThread, weekday.task);
    await cards(page)
      .first()
      .getByRole("link", { name: copy.openTask })
      .click();
    await page.waitForURL(
      `**/workspace/scheduled-tasks?task_id=${weekday.task.id}`,
    );
    await expect(page.getByTestId("scheduled-task-detail")).toHaveAttribute(
      "data-task-id",
      weekday.task.id,
    );
  });

  test(`${lang}: the per-minute card follows the task to Paused by agent without a reload`, async ({
    page,
  }) => {
    // The afternoon of the recording (16:48 Asia/Shanghai is 08:48 UTC).
    await page.clock.install({ time: new Date("2026-10-06T09:00:00Z") });
    await openChat(page, lang, minute.chatThread, freshMinuteTask());
    const card = cards(page);
    await expect(card).toHaveCount(1);
    await expect(card.getByTestId("scheduled-task-card-status")).toHaveText(
      copy.active,
    );
    await expect(card.getByTestId("scheduled-task-card-schedule")).toHaveText(
      copy.everyMinute,
    );
    // The recorded final state: run 2 asked the schedule to stop.
    await page.route(`**/api/scheduled-tasks/${minute.task.id}`, (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: minute.task })
        : route.fallback(),
    );
    await page.clock.fastForward(16_000);
    await expect(card.getByTestId("scheduled-task-card-status")).toHaveText(
      copy.pausedByAgent,
    );
    await expect(card.getByTestId("scheduled-task-card-stops")).toContainText(
      copy.reached,
    );
    await expectNoRawIdentifiers(card);
  });
}
