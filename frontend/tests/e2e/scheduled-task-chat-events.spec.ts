import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  mockLangGraphAPI,
  type MockScheduledTask,
  type MockScheduledTaskEvent,
  type MockThread,
} from "./utils/mock-api";
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
    label: "Scheduled task update",
    stopped: (title: string, condition: string) =>
      `${title} was paused by the agent. Stop condition met: ${condition}`,
    autoPaused: (title: string) =>
      `${title} was paused automatically: 3 runs in a row missed the goal.`,
    finished: (title: string) => `${title} finished: all 5 runs are done.`,
    seeThatRun: "See that run",
    openTask: "Open task",
    pausedByAgent: "Paused by agent",
    taskGone: "This task no longer exists.",
  },
  zh: {
    label: "定时任务通知",
    // A Chinese title takes no space before the predicate.
    stopped: (title: string, condition: string) =>
      `${title}已由智能体暂停。停止条件已满足：${condition}`,
    autoPaused: (title: string) => `${title}已自动暂停：连续 3 次未达成目标。`,
    finished: (title: string) => `${title}已结束：5 次运行已全部完成。`,
    seeThatRun: "查看那次运行",
    openTask: "查看任务",
    pausedByAgent: "已由智能体暂停",
    taskGone: "这个任务已不存在。",
  },
} as const;

/** The recorded task right after creation: active, nothing run yet. */
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

/** An unrelated page-created task, so the tasks page is not empty. */
function otherTask(take: ScheduledTake): MockScheduledTask {
  return {
    ...take.task,
    id: "task-0d1c2b3a4f5e6d7c8b9a0f1e2d3c4b5a",
    title: take.lang === "zh" ? "每周摘要" : "Weekly digest",
    origin_thread_id: null,
    thread_id: null,
    status: "enabled",
  };
}

/** Run id every message of the recorded origin chat carries in the mock. */
const chatRunId = (take: ScheduledTake) => `run-${take.chatThread.thread_id}`;

function stopEvent(
  take: ScheduledTake,
  overrides: Partial<MockScheduledTaskEvent> = {},
): MockScheduledTaskEvent {
  return {
    id: "evt-7a1f0c9e5b2d4e8f9a3b6c1d0e2f4a5b",
    task_id: take.task.id,
    event: "task_stopped",
    reason_code: "agent_stop",
    task_title: take.task.title,
    stop_condition: take.task.stop_condition ?? null,
    run_thread_id: take.runThread.thread_id,
    run_number: 2,
    run_status: "success",
    max_runs: take.task.max_runs ?? null,
    schedule_type: take.task.schedule_type,
    after_run_id: chatRunId(take),
    created_at: "2026-10-05T12:22:40+00:00",
    ...overrides,
  };
}

/** The origin chat with one run per turn ("create", then "trial"). */
function chatWithRunPerTurn(take: ScheduledTake): MockThread {
  const messages = take.chatThread.messages ?? [];
  const trialStart = messages.findIndex(
    (message, index) =>
      index > 0 && (message as { type?: string }).type === "human",
  );
  return {
    ...take.chatThread,
    messages: messages.map((message, index) => ({
      ...(message as Record<string, unknown>),
      run_id: index < trialStart ? "run-create" : "run-trial",
    })),
  };
}

/** The user's second question in the recorded chat ("Run it now"). */
function trialQuestion(take: ScheduledTake): string {
  const humans = (take.chatThread.messages ?? []).filter(
    (message) => (message as { type?: string }).type === "human",
  );
  const content = (humans[1] as { content?: unknown } | undefined)?.content;
  return typeof content === "string" ? content : "";
}

const lines = (page: Page) => page.getByTestId("scheduled-task-event-line");
const cards = (page: Page) => page.getByTestId("scheduled-task-card");

/** Index of the message group a node is rendered in. */
function groupIndexOf(locator: Locator): Promise<number> {
  return locator.evaluate((node) =>
    Number(
      node.closest<HTMLElement>("[data-message-group-index]")?.dataset
        .messageGroupIndex ?? -1,
    ),
  );
}

function lastGroupIndex(page: Page): Promise<number> {
  return conversation(page)
    .locator("[data-message-group-index]")
    .last()
    .evaluate((node) =>
      Number((node as HTMLElement).dataset.messageGroupIndex),
    );
}

async function openChat(
  page: Page,
  take: ScheduledTake,
  {
    tasks = [freshTask(take)],
    events = [],
    chat = take.chatThread,
  }: {
    tasks?: MockScheduledTask[];
    events?: MockScheduledTaskEvent[];
    chat?: MockThread;
  } = {},
) {
  await setLocaleCookie(page, take.lang);
  const api = mockLangGraphAPI(page, {
    threads: [chat, take.runThread],
    scheduledTasks: tasks,
    scheduledTaskRuns: { [take.task.id]: take.runs },
    scheduledTaskEvents: { [take.chatThread.thread_id]: events },
  });
  await page.goto(`/workspace/chats/${take.chatThread.thread_id}`);
  await expect(cards(page).first()).toBeVisible();
  return api;
}

for (const name of ["en-3", "zh-1"] as const) {
  const take = scheduledTake(name);
  const copy = COPY[take.lang];
  const condition = take.task.stop_condition ?? "";

  test(`${name}: a pause by the agent appears as a line at the end of the chat, without a reload`, async ({
    page,
  }) => {
    await page.clock.install();
    const api = await openChat(page, take);
    await expect(lines(page)).toHaveCount(0);

    // The recorded final state: run 2 asked the schedule to stop, and the
    // backend wrote the event in the same transaction.
    api.setScheduledTasks([take.task]);
    api.setScheduledTaskEvents(take.chatThread.thread_id, [stopEvent(take)]);
    await page.clock.fastForward(16_000);

    await expect(
      cards(page).last().getByTestId("scheduled-task-card-status"),
    ).toHaveText(copy.pausedByAgent);
    await expect(lines(page)).toHaveCount(1);
    const line = page.getByRole("note", { name: copy.label });
    await expect(line).toBeVisible();
    await expect(line.getByTestId("scheduled-task-event-text")).toContainText(
      copy.stopped(take.task.title, condition),
    );
    await expect(line.locator("strong")).toHaveText(take.task.title);
    await expect(line).toHaveAttribute("data-task-id", take.task.id);

    // At the end of the last turn, after the trial card.
    expect(await groupIndexOf(line)).toBe(await lastGroupIndex(page));
    expect(
      await cards(page)
        .last()
        .evaluate(
          (card, other) =>
            Boolean(
              card.compareDocumentPosition(other!) &
              Node.DOCUMENT_POSITION_FOLLOWING,
            ),
          await line.elementHandle(),
        ),
    ).toBe(true);
    await expectNoRawIdentifiers(line);
    await expectNoRawIdentifiers(conversation(page));
  });

  test(`${name}: See that run opens the run's chat`, async ({ page }) => {
    await openChat(page, take, {
      tasks: [take.task],
      events: [stopEvent(take)],
    });
    const link = lines(page).getByRole("link", { name: copy.seeThatRun });
    await expect(link).toHaveAttribute(
      "href",
      `/workspace/chats/${take.runThread.thread_id}`,
    );
    await link.click();
    await page.waitForURL(`**/workspace/chats/${take.runThread.thread_id}`);
    await expect(page.getByTestId("scheduled-run-prompt")).toBeVisible();
  });

  test(`${name}: a line follows its run's turn, and one without an anchor goes to the tail`, async ({
    page,
  }) => {
    await openChat(page, take, {
      tasks: [take.task],
      chat: chatWithRunPerTurn(take),
      events: [
        stopEvent(take, {
          id: "evt-tail",
          after_run_id: "run-on-a-branch-this-chat-no-longer-shows",
        }),
        stopEvent(take, {
          id: "evt-anchored",
          event: "task_paused",
          reason_code: "consecutive_unmet",
          run_status: "unmet",
          after_run_id: "run-create",
          created_at: "2026-10-05T12:21:00+00:00",
        }),
      ],
    });
    await expect(lines(page)).toHaveCount(2);
    const anchored = page.locator('[data-event-id="evt-anchored"]');
    const tail = page.locator('[data-event-id="evt-tail"]');
    await expect(anchored).toContainText(copy.autoPaused(take.task.title));

    // Anchored: the end of the "create" turn, right before the next question.
    const anchoredGroup = await groupIndexOf(anchored);
    expect(anchoredGroup).toBeLessThan(await lastGroupIndex(page));
    const nextGroupText = await anchored.evaluate(
      (node) =>
        node.closest("[data-message-group-index]")?.nextElementSibling
          ?.textContent ?? "",
    );
    expect(nextGroupText).toContain(trialQuestion(take));
    expect(await groupIndexOf(cards(page).first())).toBeLessThanOrEqual(
      anchoredGroup,
    );
    expect(await groupIndexOf(cards(page).last())).toBeGreaterThan(
      anchoredGroup,
    );

    // No message carries the anchor: the tail.
    expect(await groupIndexOf(tail)).toBe(await lastGroupIndex(page));
  });

  test(`${name}: two events of one task stay in the order they happened`, async ({
    page,
  }) => {
    await openChat(page, take, {
      tasks: [take.task],
      events: [
        // Served newest first on purpose; the chat orders by time.
        stopEvent(take, {
          id: "evt-finished",
          event: "task_finished",
          reason_code: "max_runs",
          max_runs: 5,
          run_thread_id: null,
          created_at: "2026-10-05T13:30:00+00:00",
        }),
        stopEvent(take, { id: "evt-stopped" }),
      ],
    });
    await expect(lines(page)).toHaveCount(2);
    await expect(lines(page).nth(0)).toHaveAttribute(
      "data-event-id",
      "evt-stopped",
    );
    await expect(lines(page).nth(1)).toHaveAttribute(
      "data-event-id",
      "evt-finished",
    );
    await expect(lines(page).nth(1)).toContainText(
      copy.finished(take.task.title),
    );
    await expect(
      lines(page).nth(1).getByRole("link", { name: copy.openTask }),
    ).toBeVisible();
    await expectNoRawIdentifiers(conversation(page));
  });

  test(`${name}: the line stays after the task is deleted, and Open task shows it is gone`, async ({
    page,
  }) => {
    const pausedEvent = stopEvent(take, {
      id: "evt-paused",
      event: "task_paused",
      reason_code: "consecutive_unmet",
      run_status: "unmet",
    });
    const api = await openChat(page, take, {
      tasks: [take.task, otherTask(take)],
      events: [pausedEvent],
    });
    await expect(lines(page)).toHaveCount(1);

    api.setScheduledTasks([otherTask(take)]);
    await page.reload();
    await expect(cards(page).first()).toHaveAttribute("data-state", "deleted");
    await expect(lines(page)).toHaveCount(1);
    await expect(lines(page)).toContainText(copy.autoPaused(take.task.title));

    await lines(page).getByRole("link", { name: copy.openTask }).click();
    await page.waitForURL(
      `**/workspace/scheduled-tasks?task_id=${take.task.id}`,
    );
    await expect(page.getByTestId("scheduled-task-link-missing")).toHaveText(
      copy.taskGone,
    );
  });
}
