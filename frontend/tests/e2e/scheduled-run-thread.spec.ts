import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";
import { expectNoRawIdentifiers } from "./utils/readable";
import {
  conversation,
  liveMinuteTake,
  LOCALES,
  setLocaleCookie,
} from "./utils/scheduled-fixtures";

test.describe.configure({ mode: "serial" });

// Recorded live (fixtures/scheduled/live-minute.json): scheduled run 2 of the
// per-minute checklist task, where the agent found the list done and paused it.
const take = liveMinuteTake();
const threadPath = `/workspace/chats/${take.runThread.thread_id}`;

const COPY = {
  en: {
    header: "Scheduled run",
    run: "· run 2",
    instructions: "Task instructions (sent automatically)",
    stops: `Stops when: ${take.task.stop_condition}`,
    button: "Scheduled task",
    stopStep: "Paused this scheduled task (takes effect when this run ends)",
  },
  zh: {
    header: "定时运行",
    run: "· 第 2 次",
    instructions: "任务指令（自动发送）",
    stops: `何时停止：${take.task.stop_condition}`,
    button: "所属定时任务",
    stopStep: "已暂停此定时任务（本次运行结束后生效）",
  },
} as const;

function mockRunThread(page: Page) {
  mockLangGraphAPI(page, {
    threads: [take.runThread],
    scheduledTasks: [take.task],
    scheduledTaskRuns: { [take.task.id]: take.runs },
  });
}

for (const lang of LOCALES) {
  const copy = COPY[lang];

  test(`${lang}: a run conversation shows one scheduled prompt block`, async ({
    page,
  }) => {
    await setLocaleCookie(page, lang);
    mockRunThread(page);
    await page.goto(threadPath);

    const prompt = page.getByTestId("scheduled-run-prompt");
    await expect(prompt).toHaveCount(1);
    await expect(prompt).toContainText(copy.header);
    await expect(prompt).toContainText(`${take.task.title} ${copy.run}`);
    await expect(conversation(page)).not.toContainText(
      "Stop rule from the user",
    );
    await prompt.getByRole("button", { name: copy.instructions }).click();
    await expect(prompt).toContainText(copy.stops);
    await expect(prompt.getByTestId("scheduled-run-instructions")).toHaveText(
      take.task.prompt,
    );
    await expectNoRawIdentifiers(prompt);
    // The agent's recorded final answer is the run's last word.
    await expect(conversation(page)).toContainText(
      "已按停止规则暂停该定时任务",
    );
  });

  test(`${lang}: the header button opens the run's task`, async ({ page }) => {
    await setLocaleCookie(page, lang);
    mockRunThread(page);
    await page.goto(threadPath);
    const button = page.getByTestId("thread-scheduled-tasks-button");
    await expect(button).toHaveText(copy.button);
    await button.click();
    await page.waitForURL(
      `**/workspace/scheduled-tasks?task_id=${take.task.id}`,
    );
    await expect(page.getByTestId("scheduled-task-detail")).toHaveAttribute(
      "data-task-id",
      take.task.id,
    );
  });

  test(`${lang}: the self-stop reads as a human step`, async ({ page }) => {
    await setLocaleCookie(page, lang);
    mockRunThread(page);
    await page.goto(threadPath);
    await expect(page.getByText(copy.stopStep)).toBeVisible();
    await expect(conversation(page)).not.toContainText("stop_scheduled_task");
  });
}

test("a rejoined active run still shows its launch once", async ({ page }) => {
  // The run is still going: the final answer has not been written yet.
  const messages = (take.runThread.messages ?? []).slice(0, -1);
  const launched = messages.find(
    (message) => (message as { type?: string }).type === "human",
  ) as { id: string };
  const thread = { ...take.runThread, messages };
  mockLangGraphAPI(page, {
    threads: [thread],
    scheduledTasks: [{ ...take.task, status: "enabled", last_error: null }],
    scheduledTaskRuns: { [take.task.id]: take.runs },
  });
  const runId = "active-scheduled-run";
  await page.route(
    new RegExp(`/threads/${thread.thread_id}/runs(\\?|$)`),
    (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            json: [
              {
                run_id: runId,
                thread_id: thread.thread_id,
                assistant_id: "lead_agent",
                status: "running",
                metadata: {},
                kwargs: {},
                created_at: "2026-10-06T08:48:52Z",
                updated_at: "2026-10-06T08:48:52Z",
              },
            ],
          })
        : route.fallback(),
  );
  // The run's input is the launched message under its stable id; the
  // durable state already holds the hidden copy and the visible `__user` one.
  await page.route(
    new RegExp(`/threads/${thread.thread_id}/runs/${runId}(\\?|$)`),
    (route) =>
      route.fulfill({
        json: {
          run_id: runId,
          thread_id: thread.thread_id,
          status: "running",
          kwargs: {
            input: {
              messages: [
                {
                  ...launched,
                  id: launched.id.replace(/__user$/, ""),
                },
              ],
            },
          },
        },
      }),
  );
  await page.route(
    new RegExp(`/threads/${thread.thread_id}/runs/${runId}/stream`),
    (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "event: end\ndata: null\n\n",
      }),
  );

  const joined = page.waitForRequest((request) =>
    request.url().includes(`/runs/${runId}/stream`),
  );
  await page.goto(`/workspace/chats/${thread.thread_id}`);
  await expect(page.getByTestId("scheduled-run-prompt")).toHaveCount(1);
  await joined;
  // Give the rejoin time to hydrate and settle, then check again.
  await page.waitForTimeout(1500);
  await expect(page.getByTestId("scheduled-run-prompt")).toHaveCount(1);
  await expect(conversation(page)).not.toContainText("Stop rule from the user");
});
