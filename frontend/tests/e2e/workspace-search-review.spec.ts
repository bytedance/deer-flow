import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

for (const agentName of [undefined, "researcher"]) {
  test(`new submissions leave historical search: ${agentName ?? "default"}`, async ({
    page,
  }) => {
    test.setTimeout(60000);
    mockLangGraphAPI(page, {
      agents: [{ name: "researcher" }],
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Search chat",
          agent_name: agentName,
          messages: [{ id: "old", type: "ai", content: "older answer" }],
        },
      ],
    });
    const pathname = agentName
      ? `/workspace/agents/${agentName}/chats/${MOCK_THREAD_ID}`
      : `/workspace/chats/${MOCK_THREAD_ID}`;
    await page.route("**/api/search", (route) =>
      route.fulfill({
        json: {
          items: [
            {
              type: "message",
              thread_id: MOCK_THREAD_ID,
              title: "Historical match",
              agent_name: agentName,
              message_id: "old",
              seq: 1,
              role: "assistant",
              snippet: [{ text: "older answer" }],
            },
          ],
          cursor: null,
          indexing: false,
          messages_available: true,
        },
      }),
    );
    await page.route("**/messages/around?**", (route) =>
      route.fulfill({
        json: {
          messages: [
            {
              thread_id: MOCK_THREAD_ID,
              message_id: "old",
              seq: 1,
              role: "assistant",
              text: "older answer",
            },
          ],
          target_seq: 1,
          has_before: false,
          has_after: false,
        },
      }),
    );
    await page.goto(pathname);
    const composer = page.getByRole("textbox", {
      name: "How can I assist you today?",
    });
    await expect(composer).toBeEditable();
    const first = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && r.url().includes("/runs/stream"),
    );
    await composer.fill("first turn");
    await composer.press("Enter");
    await (await first).finished();
    await expect(
      page.getByRole("button", { name: "Submit", exact: true }),
    ).toBeEnabled();
    await page.keyboard.press("ControlOrMeta+k");
    const dialog = page.getByRole("dialog", { name: "Search conversations" });
    await dialog.getByPlaceholder("Search titles and messages…").fill("older");
    await dialog
      .getByRole("option")
      .filter({ hasText: "Historical match" })
      .click();
    await expect(page.getByTestId("search-message-window")).toBeVisible();
    const second = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && r.url().includes("/runs/stream"),
    );
    await composer.fill("second turn");
    await composer.press("Enter");
    await (await second).finished();
    await expect(page).not.toHaveURL(/message=old/);
    await expect(page.getByTestId("search-message-window")).toHaveCount(0);
    await expect(page.getByText("second turn", { exact: true })).toBeVisible();
  });
}

test("return to latest preserves unrelated parameters without URLSearchParams.size", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Audit" }],
  });
  await page.addInitScript(() =>
    Object.defineProperty(URLSearchParams.prototype, "size", {
      configurable: true,
      get: () => undefined,
    }),
  );
  await page.route("**/messages/around?**", (route) =>
    route.fulfill({
      json: {
        messages: [
          {
            thread_id: MOCK_THREAD_ID,
            message_id: "old",
            seq: 1,
            role: "assistant",
            text: "Old text",
          },
        ],
        target_seq: 1,
        has_before: false,
        has_after: false,
      },
    }),
  );
  await page.goto(
    `/workspace/chats/${MOCK_THREAD_ID}?message=old&message_seq=1&custom=keep`,
  );
  await expect(page.getByTestId("search-message-window")).toBeVisible();
  await page.getByRole("button", { name: "Return to latest messages" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/workspace/chats/${MOCK_THREAD_ID}\\?custom=keep$`),
  );
});

test("historical markdown resolves thread artifact links and images", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Artifacts" }],
  });
  await page.route("**/messages/around?**", (route) =>
    route.fulfill({
      json: {
        messages: [
          {
            thread_id: MOCK_THREAD_ID,
            message_id: "old",
            seq: 1,
            role: "assistant",
            text: "[Report](/mnt/user-data/outputs/report.md)\n\n![Chart](/mnt/user-data/outputs/chart.png)",
          },
        ],
        target_seq: 1,
        has_before: false,
        has_after: false,
      },
    }),
  );
  await page.goto(
    `/workspace/chats/${MOCK_THREAD_ID}?message=old&message_seq=1`,
  );
  const window = page.getByTestId("search-message-window");
  await expect(
    window.getByRole("link", { name: "Report", exact: true }),
  ).toHaveAttribute(
    "href",
    /\/api\/threads\/[^/]+\/artifacts\/mnt\/user-data\/outputs\/report.md$/,
  );
  await expect(window.getByRole("img", { name: "Chart" })).toHaveAttribute(
    "src",
    /\/api\/threads\/[^/]+\/artifacts\/mnt\/user-data\/outputs\/chart.png$/,
  );
});

test("command mode reports a query without matching commands", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.goto("/workspace/chats/new");
  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  await dialog
    .getByPlaceholder("Search titles and messages…")
    .fill(">no-such-command");
  await expect(dialog.getByRole("status")).toBeVisible();
  await expect(dialog.getByRole("option")).toHaveCount(0);
});
