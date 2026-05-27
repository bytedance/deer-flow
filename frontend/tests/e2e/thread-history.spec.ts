import { expect, test } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
} from "./utils/mock-api";

const threads = () => [
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

test.describe("Thread history", () => {
  test("sidebar shows existing threads", async ({ page }) => {
    mockLangGraphAPI(page, { threads: threads() });

    await page.goto("/workspace/chats/new");

    // Both thread titles should appear in the sidebar
    await expect(page.getByText("First conversation")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Second conversation")).toBeVisible();
  });

  test("clicking a thread in sidebar navigates to it", async ({ page }) => {
    mockLangGraphAPI(page, { threads: threads() });

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

  test("sidebar can archive a thread", async ({ page }) => {
    mockLangGraphAPI(page, { threads: threads() });

    await page.goto("/workspace/chats/new");

    const firstThread = page.locator('[data-sidebar="menu-item"]', {
      hasText: "First conversation",
    });
    await expect(firstThread).toBeVisible({ timeout: 15_000 });
    await firstThread.hover();
    await firstThread.getByRole("button", { name: "More" }).click();
    await expect(page.getByRole("menuitem", { name: "Delete" })).toHaveCount(0);
    await page.getByRole("menuitem", { name: "Archive" }).click();

    await expect(page.getByText("First conversation")).toHaveCount(0);
    await expect(page.getByText("Second conversation")).toBeVisible();
  });

  test("existing thread loads historical messages", async ({ page }) => {
    mockLangGraphAPI(page, { threads: threads() });

    // Navigate directly to an existing thread
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    // The historical AI response should be displayed
    await expect(
      page.getByText("Response in thread First conversation"),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("chats list page shows all threads", async ({ page }) => {
    mockLangGraphAPI(page, { threads: threads() });

    await page.goto("/workspace/chats");

    // Both threads should be listed in the main content area
    const main = page.locator("main");
    await expect(main.getByText("First conversation")).toBeVisible({
      timeout: 15_000,
    });
    await expect(main.getByText("Second conversation")).toBeVisible();
  });

  test("chats list page can select all and delete selected threads", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: threads() });

    await page.goto("/workspace/chats");

    const main = page.locator("main");
    await expect(main.getByText("First conversation")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: "Select all" }).click();
    await expect(page.getByText("Selected 2")).toBeVisible();
    await page.getByRole("button", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(main.getByText("First conversation")).toHaveCount(0);
    await expect(main.getByText("Second conversation")).toHaveCount(0);
  });

  test("chats list page can shift-select and archive selected threads", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: threads() });

    await page.goto("/workspace/chats");

    const main = page.locator("main");
    await expect(main.getByText("First conversation")).toBeVisible({
      timeout: 15_000,
    });
    await main.getByRole("checkbox", { name: "First conversation" }).click();
    await main
      .getByRole("checkbox", { name: "Second conversation" })
      .click({ modifiers: ["Shift"] });
    await expect(page.getByText("Selected 2")).toBeVisible();
    await page.getByRole("button", { name: "Archive" }).click();

    await expect(main.getByText("First conversation")).toHaveCount(0);
    await expect(main.getByText("Second conversation")).toHaveCount(0);
    await page.getByRole("tab", { name: "Archived" }).click();
    await expect(main.getByText("First conversation")).toBeVisible();
    await expect(main.getByText("Second conversation")).toBeVisible();
  });

  test("chats list page can delete a thread", async ({ page }) => {
    mockLangGraphAPI(page, { threads: threads() });

    await page.goto("/workspace/chats");

    const main = page.locator("main");
    const row = main.locator("div.border-b", {
      hasText: "First conversation",
    });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.hover();
    await row.getByRole("button", { name: "More" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    await expect(main.getByText("First conversation")).toHaveCount(0);
    await expect(main.getByText("Second conversation")).toBeVisible();
  });

  test("chats list page can archive and restore a thread", async ({ page }) => {
    mockLangGraphAPI(page, { threads: threads() });

    await page.goto("/workspace/chats");

    const main = page.locator("main");
    const row = main.locator("div.border-b", {
      hasText: "First conversation",
    });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.hover();
    await row.getByRole("button", { name: "More" }).click();
    await page.getByRole("menuitem", { name: "Archive" }).click();

    await expect(main.getByText("First conversation")).toHaveCount(0);
    await page.getByRole("tab", { name: "Archived" }).click();
    await expect(main.getByText("First conversation")).toBeVisible();

    await row.hover();
    await row.getByRole("button", { name: "More" }).click();
    await page.getByRole("menuitem", { name: "Restore" }).click();

    await expect(main.getByText("First conversation")).toHaveCount(0);
    await page.getByRole("tab", { name: "Chats" }).click();
    await expect(main.getByText("First conversation")).toBeVisible();
  });
});
