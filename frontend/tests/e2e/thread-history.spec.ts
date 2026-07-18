import { expect, test, type Route } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
} from "./utils/mock-api";

const THREADS = [
  {
    thread_id: MOCK_THREAD_ID,
    title: "First conversation",
    updated_at: "2025-06-01T12:00:00Z",
  },
  {
    thread_id: MOCK_THREAD_ID_2,
    title: "Second conversation",
    updated_at: "2025-06-02T12:00:00Z",
  },
];
const DEMO_THREAD_ID = "7cfa5f8f-a2f8-47ad-acbd-da7137baf990";
const SVG_PROMPT_THREAD_ID = "00000000-0000-0000-0000-000000000777";
const SVG_PROMPT_MARKER = "LEAK-STRICT-SVG-PROMPT-SHOULD-DISAPPEAR";
const OPTIMISTIC_PROMPT_MARKER = "LEAK-OPTIMISTIC-SVG-PROMPT-SHOULD-DISAPPEAR";

test.describe("Thread history", () => {
  test("sidebar shows existing threads", async ({ page }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats/new");

    // Both thread titles should appear in the sidebar
    await expect(page.getByText("First conversation")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Second conversation")).toBeVisible();
  });

  test("clicking a thread in sidebar navigates to it", async ({ page }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats/new");

    // Wait for sidebar to populate
    const firstThread = page.getByText("First conversation");
    await expect(firstThread).toBeVisible({ timeout: 15_000 });

    // Click on the first thread
    await firstThread.click();

    // Should navigate to that thread's URL
    await page.waitForURL(`**/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID));
  });

  test("clicking blank space in a sidebar thread row navigates to it", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const firstThreadItem = sidebar
      .locator("[data-sidebar='menu-item']")
      .filter({ hasText: "First conversation" })
      .first();
    await expect(firstThreadItem).toBeVisible({ timeout: 15_000 });

    const firstThreadLink = firstThreadItem.getByRole("link");
    await expect(firstThreadLink).toBeVisible();

    const box = await firstThreadLink.boundingBox();
    expect(box).not.toBeNull();
    if (!box) {
      return;
    }

    await firstThreadLink.click({ position: { x: 4, y: box.height / 2 } });

    await page.waitForURL(`**/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID));
  });

  test("existing thread loads historical messages", async ({ page }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    // Navigate directly to an existing thread
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    // The historical AI response should be displayed
    await expect(
      page.getByText("Response in thread First conversation"),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("input box recalls previous prompts with arrow keys", async ({
    page,
  }) => {
    const firstPrompt = "Summarize the latest quarterly report";
    const secondPrompt = "Turn the summary into an action plan";

    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Prompt history conversation",
          updated_at: "2025-06-03T12:00:00Z",
          messages: [
            {
              type: "human",
              id: "msg-human-prompt-history-1",
              content: [{ type: "text", text: firstPrompt }],
            },
            {
              type: "ai",
              id: "msg-ai-prompt-history-1",
              content: "First answer",
            },
            {
              type: "human",
              id: "msg-human-prompt-history-2",
              content: [{ type: "text", text: secondPrompt }],
            },
            {
              type: "ai",
              id: "msg-ai-prompt-history-2",
              content: "Second answer",
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("Second answer")).toBeVisible({
      timeout: 15_000,
    });

    const textarea = page.locator("textarea[name='message']");
    await expect(textarea).toBeVisible();

    await textarea.focus();
    await textarea.press("ArrowUp");
    await expect(textarea).toHaveValue(secondPrompt);

    await textarea.press("ArrowUp");
    await expect(textarea).toHaveValue(firstPrompt);

    await textarea.press("ArrowDown");
    await expect(textarea).toHaveValue(secondPrompt);

    await textarea.press("ArrowDown");
    await expect(textarea).toHaveValue("");

    await textarea.fill("draft should not be overwritten");
    await textarea.press("ArrowUp");
    await expect(textarea).toHaveValue("draft should not be overwritten");
  });

  test("deleting an inactive chat keeps the current chat open", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(
      page.getByText("Response in thread First conversation"),
    ).toBeVisible({ timeout: 15_000 });

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const inactiveThreadItem = sidebar
      .locator("[data-sidebar='menu-item']")
      .filter({
        has: page.getByRole("button", { name: /more/i }),
        hasText: "Second conversation",
      })
      .first();
    await expect(inactiveThreadItem).toBeVisible();
    await inactiveThreadItem.hover();
    await inactiveThreadItem.getByRole("button", { name: /more/i }).click();
    await page.getByRole("menuitem", { name: /delete/i }).click();

    await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID));
    await expect(
      page.getByText("Response in thread First conversation"),
    ).toBeVisible();
    await expect(sidebar.getByText("Second conversation")).toHaveCount(0);
  });

  test("new chat does not show previous thread messages after client-side navigation", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: SVG_PROMPT_THREAD_ID,
          title: "SVG artifact prompt",
          updated_at: "2025-06-03T12:00:00Z",
          messages: [
            {
              type: "human",
              id: "msg-human-svg-prompt",
              content: [
                {
                  type: "text",
                  text: `请严格执行：\n1. 使用 write_file 创建 /mnt/user-data/outputs/shared.svg，内容包含 ${SVG_PROMPT_MARKER}\n2. 最终回复只输出 Markdown 图片。`,
                },
              ],
            },
            {
              type: "ai",
              id: "msg-ai-svg-prompt",
              content: "![shared artifact](/mnt/user-data/outputs/shared.svg)",
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${SVG_PROMPT_THREAD_ID}`);
    await expect(page.getByText(SVG_PROMPT_MARKER)).toBeVisible({
      timeout: 15_000,
    });

    await page
      .locator("[data-sidebar='sidebar'] a[href='/workspace/chats/new']")
      .click();
    await page.waitForURL("**/workspace/chats/new");

    await expect(page.getByText(SVG_PROMPT_MARKER)).toBeHidden();
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible();
  });

  test("new chat does not show previous optimistic user message after client-side navigation", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID_2,
          title: "Destination conversation",
          updated_at: "2025-06-04T12:00:00Z",
        },
      ],
    });

    const metadataOnlyStream = async (route: Route) => {
      const body = [
        {
          event: "metadata",
          data: {
            run_id: "00000000-0000-0000-0000-000000000778",
            thread_id: MOCK_THREAD_ID,
          },
        },
        { event: "end", data: {} },
      ]
        .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
        .join("");

      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body,
      });
    };

    await page.route("**/api/langgraph/runs/stream", metadataOnlyStream);
    await page.route(
      "**/api/langgraph/threads/*/runs/stream",
      metadataOnlyStream,
    );

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill(
      `请严格执行：使用 write_file 创建 shared.svg，内容包含 ${OPTIMISTIC_PROMPT_MARKER}。`,
    );
    await textarea.press("Enter");

    await expect(page.getByText(OPTIMISTIC_PROMPT_MARKER)).toBeVisible();

    await page.getByText("Destination conversation").click();
    await page.waitForURL(`**/workspace/chats/${MOCK_THREAD_ID_2}`);
    await expect(page.getByText(OPTIMISTIC_PROMPT_MARKER)).toHaveCount(0);

    await page
      .locator("[data-sidebar='sidebar'] a[href='/workspace/chats/new']")
      .click();
    await page.waitForURL("**/workspace/chats/new");

    await expect(page.getByText(OPTIMISTIC_PROMPT_MARKER)).toHaveCount(0);
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible();
  });

  test("new chat resets immediately after a history-only thread URL update", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Message that must disappear in the next new chat");
    await textarea.press("Enter");
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 15_000,
    });

    // A newly created chat changes the URL with history.replaceState so the
    // active stream is not remounted. Reproduce that history-only transition:
    // the canonical pathname becomes the UUID while useParams can stay "new".
    await page.evaluate((threadId) => {
      history.replaceState(null, "", `/workspace/chats/${threadId}`);
    }, MOCK_THREAD_ID);

    const newChatLink = page.locator(
      "[data-sidebar='sidebar'] a[href='/workspace/chats/new']",
    );
    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID}$`),
    );
    await expect(newChatLink).toHaveAttribute("data-active", "false");

    // One click must reset the chat without a second click or unrelated UI
    // interaction forcing another render.
    await newChatLink.click();
    await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
    await expect(page.getByText("Hello from DeerFlow!")).toHaveCount(0);
    await expect(textarea).toBeVisible();
  });

  test("deleting the active newly created chat returns to the new chat screen", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.route(/\/api\/threads\/[^/]+$/, (route) => {
      if (route.request().method() === "DELETE") {
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Local cleanup failed" }),
        });
      }
      return route.fallback();
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("What should disappear after deletion?");
    await textarea.press("Enter");

    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 15_000,
    });

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const recentThreadItem = sidebar
      .locator("[data-sidebar='menu-item']")
      .filter({
        has: page.getByRole("button", { name: /more/i }),
        hasText: "New Chat",
      })
      .first();
    await expect(recentThreadItem).toBeVisible();
    await recentThreadItem.hover();
    await recentThreadItem.getByRole("button", { name: /more/i }).click();
    await page.getByRole("menuitem", { name: /delete/i }).click();

    await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
    await expect(page.getByText("Previous question")).toHaveCount(0);
    await expect(page.getByText("Hello from DeerFlow!")).toHaveCount(0);
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible();

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.waitForURL("**/workspace/chats/new");
    await expect(page.getByText("Hello from DeerFlow!")).toHaveCount(0);
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible();
  });

  test("mock thread does not load real backend run history", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: DEMO_THREAD_ID,
          title: "Forecasting 2026 Trends and Opportunities",
          updated_at: "2025-06-01T12:00:00Z",
          messages: [
            {
              type: "human",
              id: `run-human-${DEMO_THREAD_ID}`,
              content: [
                {
                  type: "text",
                  text: "This run-message endpoint should not be called.",
                },
              ],
            },
          ],
        },
      ],
    });
    const backendRunHistoryUrls: string[] = [];
    await page.route(
      /\/api\/langgraph\/threads\/[^/]+\/runs(?:\?|$)/,
      (route) => {
        if (
          route.request().method() === "GET" &&
          route
            .request()
            .url()
            .includes(`/api/langgraph/threads/${DEMO_THREAD_ID}/runs`)
        ) {
          backendRunHistoryUrls.push(route.request().url());
          return route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({
              error: "mock=true must not load real runs",
            }),
          });
        }
        return route.fallback();
      },
    );
    await page.route(
      /\/api\/threads\/[^/]+\/runs\/[^/]+\/messages(?:\?|$)/,
      (route) => {
        if (
          route.request().method() === "GET" &&
          route.request().url().includes(`/api/threads/${DEMO_THREAD_ID}/runs/`)
        ) {
          backendRunHistoryUrls.push(route.request().url());
          return route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({
              error: "mock=true must not load real run messages",
            }),
          });
        }
        return route.fallback();
      },
    );

    await page.goto(`/workspace/chats/${DEMO_THREAD_ID}?mock=true`);

    await expect(
      page.getByText("What might be the trends and opportunities in 2026?"),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByText("I've created a modern, minimalist website"),
    ).toBeVisible();
    expect(backendRunHistoryUrls).toEqual([]);
  });

  test("chats list page shows all threads", async ({ page }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats");

    // Both threads should be listed in the main content area
    const main = page.locator("main");
    await expect(main.getByText("First conversation")).toBeVisible({
      timeout: 15_000,
    });
    await expect(main.getByText("Second conversation")).toBeVisible();
  });

  test("IM channel threads show their source in thread lists", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Feishu conversation",
          updated_at: "2025-06-03T12:00:00Z",
          metadata: {
            channel_source: {
              type: "im_channel",
              provider: "feishu",
              chat_id: "oc_mock",
            },
          },
        },
      ],
    });

    await page.goto("/workspace/chats/new");

    const sidebarThread = page.locator(
      `a[href='/workspace/chats/${MOCK_THREAD_ID}']`,
    );
    await expect(sidebarThread).toBeVisible({ timeout: 15_000 });
    await expect(sidebarThread.getByLabel("Feishu channel")).toBeVisible();

    await page.goto("/workspace/chats");

    const mainThread = page
      .locator("main")
      .locator(`a[href='/workspace/chats/${MOCK_THREAD_ID}']`);
    await expect(mainThread.getByText("Feishu conversation")).toBeVisible({
      timeout: 15_000,
    });
    await expect(mainThread.getByText("Feishu", { exact: true })).toBeVisible();
  });
});
