import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

test.beforeEach(async ({ page }) => {
  mockLangGraphAPI(page, {
    agents: [{ name: "researcher" }],
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Search fixture",
        agent_name: "researcher",
      },
    ],
  });
});

test("keyboard commands and Escape work without a search provider", async ({
  page,
}) => {
  await page.route("**/api/search", (route) =>
    route.fulfill({
      json: {
        items: [],
        cursor: null,
        indexing: false,
        messages_available: false,
      },
    }),
  );
  await page.goto("/workspace/chats/new");
  await expect(
    page.getByRole("textbox", { name: "How can I assist you today?" }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(
    page.getByRole("button", { name: /^Search/ }).first(),
  ).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  const input = dialog.getByPlaceholder("Search titles and messages…");
  await expect(input).toBeFocused();
  await input.fill(">settings");
  await expect(dialog.getByRole("option", { name: /Settings/ })).toBeVisible();
  await input.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("filters, stale requests, safe snippets and custom agent links", async ({
  page,
}) => {
  const requests: {
    query: string;
    types: string[];
    archived: boolean | null;
  }[] = [];
  await page.route("**/api/search", async (route) => {
    const body = route.request().postDataJSON() as (typeof requests)[number];
    requests.push(body);
    if (body.query === "old")
      await new Promise((resolve) => setTimeout(resolve, 700));
    await route.fulfill({
      json: {
        items: body.query
          ? [
              {
                type: "message",
                thread_id: MOCK_THREAD_ID,
                title: `${body.query} result`,
                agent_name: "researcher",
                archived: true,
                updated_at: "2026-10-25T08:00:00Z",
                project_id: null,
                message_id: "original/id",
                seq: 3,
                role: "assistant",
                snippet: [
                  { text: `<script>${body.query}</script>`, matched: true },
                ],
              },
            ]
          : [],
        cursor: null,
        indexing: false,
        messages_available: true,
      },
    });
  });
  await page.goto("/workspace/chats/new");
  await expect(
    page.getByRole("textbox", { name: "How can I assist you today?" }),
  ).toBeVisible({ timeout: 15_000 });
  await page
    .getByRole("button", { name: /^Search/ })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  const input = dialog.getByPlaceholder("Search titles and messages…");
  await input.fill("old");
  await expect.poll(() => requests.some((r) => r.query === "old")).toBeTruthy();
  await input.fill("latest");
  await expect(dialog.getByText("latest result")).toBeVisible();
  await expect(dialog.locator("mark")).toHaveText("<script>latest</script>");
  await dialog.getByRole("button", { name: "Messages", exact: true }).click();
  await dialog.getByRole("checkbox", { name: "Include archived" }).uncheck();
  await expect
    .poll(() => requests.at(-1))
    .toMatchObject({ query: "latest", types: ["message"], archived: false });
  await expect(dialog.getByText("old result")).toBeHidden();
  await dialog.getByRole("option").filter({ hasText: "latest result" }).click();
  await expect(page).toHaveURL(
    new RegExp(
      `/workspace/agents/researcher/chats/${MOCK_THREAD_ID}\\?message=original%2Fid&message_seq=3`,
    ),
  );
});

test("empty and error states retry without losing the query", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/search", (route) =>
    fail
      ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({
          json: {
            items: [],
            cursor: null,
            indexing: false,
            messages_available: true,
          },
        }),
  );
  await page.goto("/workspace/chats/new");
  await expect(
    page.getByRole("textbox", { name: "How can I assist you today?" }),
  ).toBeVisible({ timeout: 15_000 });
  await page
    .getByRole("button", { name: /^Search/ })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  const input = dialog.getByPlaceholder("Search titles and messages…");
  await input.fill("missing report");
  await expect(
    dialog.getByText("Search could not finish. Try again."),
  ).toBeVisible();
  fail = false;
  await dialog.getByRole("button", { name: "Try again" }).click();
  await expect(dialog.getByText(/No matches/)).toBeVisible();
  await expect(input).toHaveValue("missing report");
});

test("Chinese composition does not dispatch partial searches or select a command", async ({
  page,
}) => {
  const queries: string[] = [];
  await page.route("**/api/search", (route) => {
    queries.push((route.request().postDataJSON() as { query: string }).query);
    return route.fulfill({
      json: {
        items: [],
        cursor: null,
        indexing: false,
        messages_available: true,
      },
    });
  });
  await page.goto("/workspace/chats/new");
  await expect(
    page.getByRole("textbox", { name: "How can I assist you today?" }),
  ).toBeVisible({ timeout: 15_000 });
  await page
    .getByRole("button", { name: /^Search/ })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  const input = dialog.getByPlaceholder("Search titles and messages…");
  await input.dispatchEvent("compositionstart");
  await input.fill("baogao");
  await input.dispatchEvent("keydown", {
    key: "Enter",
    keyCode: 229,
    isComposing: true,
  });
  await expect(dialog).toBeVisible();
  await page.waitForTimeout(350);
  expect(queries).not.toContain("baogao");
  await input.fill("报告");
  await input.dispatchEvent("compositionend");
  await expect.poll(() => queries).toContain("报告");
});

test("search fits a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/search", (route) =>
    route.fulfill({
      json: {
        items: [],
        cursor: null,
        indexing: false,
        messages_available: true,
      },
    }),
  );
  await page.goto("/workspace/chats/new");
  await expect(
    page.getByRole("textbox", { name: "How can I assist you today?" }),
  ).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Toggle Sidebar" }).first().click();
  await page
    .getByRole("button", { name: /^Search/ })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  await expect(dialog).toBeVisible();
  const bounds = await dialog.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await expect(
    dialog.getByRole("checkbox", { name: "Include archived" }),
  ).toBeInViewport();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});
