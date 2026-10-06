import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, type MockThread } from "./utils/mock-api";
import { expectNoRawIdentifiers } from "./utils/readable";
import { scheduledTake, setLocaleCookie } from "./utils/scheduled-fixtures";

test.describe.configure({ mode: "serial" });

const COPY = {
  en: {
    scheduled: "Scheduled run",
    unread: "Unread",
    unreadLabel: (title: string) => `${title}, unread`,
    feishu: "From Feishu",
    feishuChip: "Feishu",
    github: "From GitHub",
  },
  zh: {
    scheduled: "定时运行",
    unread: "未读",
    unreadLabel: (title: string) => `${title}，未读`,
    feishu: "来自飞书",
    feishuChip: "飞书",
    github: "来自 GitHub",
  },
} as const;

const FEISHU_THREAD: MockThread = {
  thread_id: "4b0f3c55-0c1e-4f0a-9d7e-5f1f8f0b6e21",
  title: "Weekly numbers",
  updated_at: "2026-10-05T11:00:00Z",
  metadata: { channel_source: { type: "im_channel", provider: "feishu" } },
};

const GITHUB_THREAD: MockThread = {
  thread_id: "f7f4a0c2-6a43-4c55-b6a8-1bb2b8e2d3a9",
  title: "Review the docs PR",
  updated_at: "2026-10-05T10:00:00Z",
  metadata: {
    deerflow_origin: { kind: "github", provider: "github" },
    channel_source: { type: "im_channel", provider: "github" },
  },
};

const sidebar = (page: Page) => page.locator("[data-sidebar='sidebar']");
const sidebarRow = (page: Page, threadId: string) =>
  sidebar(page).locator(`a[href='/workspace/chats/${threadId}']`);

/** Activity-feed requests (their query strings) and full page loads. */
function trackRequests(page: Page) {
  const activity: string[] = [];
  const loads = { count: 0 };
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/thread-activity") {
      activity.push(url.search);
    }
  });
  page.on("load", () => {
    loads.count += 1;
  });
  return { activity, loads };
}

for (const name of ["en-3", "zh-1"] as const) {
  const take = scheduledTake(name);
  const copy = COPY[take.lang];
  const runTitle = take.runThread.title!;
  const runThreadId = take.runThread.thread_id;

  test(`${name}: a new scheduled run appears in the sidebar unread, and opening it clears the dot`, async ({
    page,
  }) => {
    await page.clock.install();
    await setLocaleCookie(page, take.lang);
    const requests = trackRequests(page);
    const api = mockLangGraphAPI(page, {
      threads: [take.chatThread, FEISHU_THREAD, GITHUB_THREAD],
      features: { threadActivity: { available: true } },
    });
    await page.goto(`/workspace/chats/${take.chatThread.thread_id}`);
    await expect(sidebarRow(page, take.chatThread.thread_id)).toBeVisible({
      timeout: 15_000,
    });
    // The first poll only seeds the cursor.
    await expect.poll(() => requests.activity.length).toBeGreaterThan(0);
    expect(requests.activity[0]).not.toContain("cursor=");
    await expect(sidebarRow(page, runThreadId)).toHaveCount(0);

    // The scheduler starts a run in a new thread while the user stays on
    // chat A.
    api.upsertThread({
      ...take.runThread,
      updated_at: "2099-01-01T00:00:00Z",
      metadata: {
        deerflow_origin: { kind: "schedule" },
        scheduled_task_id: take.task.id,
      },
      unread: true,
    });
    api.pushThreadActivity({ thread_id: runThreadId, status: "success" });
    const loadsBefore = requests.loads.count;
    await page.clock.fastForward(16_000);

    // Within one poll, without a reload.
    const row = sidebarRow(page, runThreadId);
    await expect(row).toBeVisible();
    expect(requests.loads.count).toBe(loadsBefore);
    await expect(row).toHaveAttribute("aria-label", copy.unreadLabel(runTitle));
    await expect(row).toContainText(runTitle);
    await expect(row.getByRole("img", { name: copy.scheduled })).toBeVisible();
    const dot = row.getByTestId("thread-unread-dot");
    await expect(dot).toBeVisible();
    await expect(dot).toHaveAttribute("title", copy.unread);
    await expectNoRawIdentifiers(sidebar(page));

    // IM and GitHub threads carry their origin too, already read.
    const feishu = sidebarRow(page, FEISHU_THREAD.thread_id);
    await expect(feishu.getByRole("img", { name: copy.feishu })).toBeVisible();
    await expect(feishu).toContainText(copy.feishuChip);
    await expect(feishu.getByTestId("thread-unread-dot")).toHaveCount(0);
    const github = sidebarRow(page, GITHUB_THREAD.thread_id);
    await expect(github.getByRole("img", { name: copy.github })).toBeVisible();

    // Opening the run marks it read on the server and the dot goes away.
    await row.click();
    await page.waitForURL(`**/workspace/chats/${runThreadId}`);
    await expect(row).toHaveAttribute("data-active", "true");
    await expect(row.getByTestId("thread-unread-dot")).toHaveCount(0);
    await page.clock.runFor(1_500);
    await expect.poll(() => api.readRequests).toEqual([runThreadId]);

    // Back on chat A, the run stays read: the cache and the server agree.
    await sidebarRow(page, take.chatThread.thread_id).click();
    await page.waitForURL(`**/workspace/chats/${take.chatThread.thread_id}`);
    await page.clock.fastForward(16_000);
    await expect(row).toBeVisible();
    await expect(row.getByTestId("thread-unread-dot")).toHaveCount(0);
    await expect(row).not.toHaveAttribute("aria-label", /./);
    expect(api.readRequests).toEqual([runThreadId]);
  });
}

test("a read on another device clears the dot after the next poll", async ({
  page,
}) => {
  await page.clock.install();
  const take = scheduledTake("en-3");
  const requests = trackRequests(page);
  const api = mockLangGraphAPI(page, {
    threads: [
      take.chatThread,
      {
        ...take.runThread,
        metadata: { deerflow_origin: { kind: "schedule" } },
        unread: true,
      },
    ],
    features: { threadActivity: { available: true } },
  });
  await page.goto(`/workspace/chats/${take.chatThread.thread_id}`);
  const row = sidebarRow(page, take.runThread.thread_id);
  await expect(row.getByTestId("thread-unread-dot")).toBeVisible({
    timeout: 15_000,
  });
  await expect.poll(() => requests.activity.length).toBeGreaterThan(0);

  // Another device opened the run: the server's read clock moves and the
  // thread is read there.
  api.upsertThread({
    ...take.runThread,
    metadata: { deerflow_origin: { kind: "schedule" } },
    unread: false,
  });
  api.bumpReadVersion();
  await page.clock.fastForward(16_000);
  await expect(row.getByTestId("thread-unread-dot")).toHaveCount(0);
  expect(api.readRequests).toEqual([]);
});

test("the chats page shows the same origin marker and unread dot", async ({
  page,
}) => {
  const take = scheduledTake("zh-1");
  await setLocaleCookie(page, "zh");
  mockLangGraphAPI(page, {
    threads: [
      {
        ...take.runThread,
        metadata: { deerflow_origin: { kind: "schedule" } },
        unread: true,
      },
      FEISHU_THREAD,
    ],
    features: { threadActivity: { available: true } },
  });
  await page.goto("/workspace/chats");
  const list = page.getByRole("tabpanel");
  const run = list.locator(
    `a[href='/workspace/chats/${take.runThread.thread_id}']`,
  );
  await expect(run).toHaveAttribute(
    "aria-label",
    COPY.zh.unreadLabel(take.runThread.title!),
    { timeout: 15_000 },
  );
  await expect(run.getByRole("img", { name: COPY.zh.scheduled })).toBeVisible();
  await expect(run.getByTestId("thread-unread-dot")).toBeVisible();
  const feishu = list.locator(
    `a[href='/workspace/chats/${FEISHU_THREAD.thread_id}']`,
  );
  await expect(feishu.getByRole("img", { name: COPY.zh.feishu })).toBeVisible();
  await expect(feishu.getByTestId("thread-unread-dot")).toHaveCount(0);
  await expectNoRawIdentifiers(list);
});

test("nothing polls thread activity when the Gateway does not offer it", async ({
  page,
}) => {
  await page.clock.install();
  const take = scheduledTake("en-3");
  const requests = trackRequests(page);
  const api = mockLangGraphAPI(page, {
    threads: [
      take.chatThread,
      {
        ...take.runThread,
        metadata: { deerflow_origin: { kind: "schedule" } },
      },
    ],
  });
  await page.goto(`/workspace/chats/${take.runThread.thread_id}`);
  const row = sidebarRow(page, take.runThread.thread_id);
  await expect(row.getByRole("img", { name: "Scheduled run" })).toBeVisible({
    timeout: 15_000,
  });
  await page.clock.fastForward(46_000);
  expect(requests.activity).toEqual([]);
  expect(api.readRequests).toEqual([]);
});
