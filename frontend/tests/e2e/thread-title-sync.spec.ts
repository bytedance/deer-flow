import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000000321";
const ORIGINAL_TITLE = "Original title";
const RENAMED_TITLE = "Renamed title";

test("renaming a thread updates the sidebar, header, and document title", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: ORIGINAL_TITLE,
        updated_at: "2026-07-05T10:00:00Z",
      },
    ],
  });

  await page.goto(`/workspace/chats/${THREAD_ID}`);
  await expect(page.getByText(ORIGINAL_TITLE).first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(page).toHaveTitle(`${ORIGINAL_TITLE} - DeerFlow`);

  const threadItem = page
    .locator(
      `a[data-sidebar="menu-button"][href="/workspace/chats/${THREAD_ID}"]`,
    )
    .locator("xpath=..");
  await threadItem.hover();
  await threadItem.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").fill(RENAMED_TITLE);
  await dialog.getByRole("button", { name: "Save" }).click();

  await expect(dialog).toBeHidden();
  await expect(threadItem).toContainText(RENAMED_TITLE);
  await expect(page.locator("header").getByText(RENAMED_TITLE)).toBeVisible();
  await expect(page).toHaveTitle(`${RENAMED_TITLE} - DeerFlow`);

  await page.reload();
  await expect(threadItem).toContainText(RENAMED_TITLE);
  await expect(page.locator("header").getByText(RENAMED_TITLE)).toBeVisible({
    timeout: 15_000,
  });
  await expect(page).toHaveTitle(`${RENAMED_TITLE} - DeerFlow`);
});

test("a stale metadata response cannot restore the old title after rename", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: ORIGINAL_TITLE,
        updated_at: "2026-07-05T10:00:00Z",
      },
    ],
  });

  let releaseStaleMetadataResponse!: () => void;
  const staleMetadataResponseGate = new Promise<void>((resolve) => {
    releaseStaleMetadataResponse = resolve;
  });
  let markStaleMetadataRequestStarted!: () => void;
  const staleMetadataRequestStarted = new Promise<void>((resolve) => {
    markStaleMetadataRequestStarted = resolve;
  });
  let markStaleMetadataResponseCompleted!: () => void;
  const staleMetadataResponseCompleted = new Promise<void>((resolve) => {
    markStaleMetadataResponseCompleted = resolve;
  });
  let releaseFreshMetadataResponse!: () => void;
  const freshMetadataResponseGate = new Promise<void>((resolve) => {
    releaseFreshMetadataResponse = resolve;
  });
  let markFreshMetadataRequestStarted!: () => void;
  const freshMetadataRequestStarted = new Promise<void>((resolve) => {
    markFreshMetadataRequestStarted = resolve;
  });
  let markFreshMetadataResponseCompleted!: () => void;
  const freshMetadataResponseCompleted = new Promise<void>((resolve) => {
    markFreshMetadataResponseCompleted = resolve;
  });
  let delayMetadataResponses = false;
  let metadataRequestCount = 0;

  await page.route("**/api/langgraph/threads/*", async (route) => {
    const url = new URL(route.request().url());
    if (
      route.request().method() !== "GET" ||
      url.pathname !== `/api/langgraph/threads/${THREAD_ID}`
    ) {
      return route.fallback();
    }

    if (!delayMetadataResponses) {
      return route.fallback();
    }

    metadataRequestCount += 1;
    if (metadataRequestCount > 1) {
      markFreshMetadataRequestStarted();
      await freshMetadataResponseGate;
      await route.fallback();
      markFreshMetadataResponseCompleted();
      return;
    }

    markStaleMetadataRequestStarted();
    await staleMetadataResponseGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        thread_id: THREAD_ID,
        created_at: "2026-07-05T10:00:00Z",
        updated_at: "2026-07-05T10:00:00Z",
        metadata: {},
        status: "idle",
        values: { title: ORIGINAL_TITLE, goal: null },
      }),
    });
    markStaleMetadataResponseCompleted();
  });

  await page.goto(`/workspace/chats/${THREAD_ID}`);
  await expect(page.locator("header").getByText(ORIGINAL_TITLE)).toBeVisible({
    timeout: 15_000,
  });

  delayMetadataResponses = true;
  await page.getByRole("link", { name: "Chats", exact: true }).click();
  await expect(page).toHaveURL(/\/workspace\/chats$/);
  await page
    .locator(
      `a[data-sidebar="menu-button"][href="/workspace/chats/${THREAD_ID}"]`,
    )
    .click();
  await staleMetadataRequestStarted;

  const threadItem = page
    .locator(
      `a[data-sidebar="menu-button"][href="/workspace/chats/${THREAD_ID}"]`,
    )
    .locator("xpath=..");
  await expect(threadItem).toContainText(ORIGINAL_TITLE);
  await threadItem.hover();
  await threadItem.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").fill(RENAMED_TITLE);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
  await expect(threadItem).toContainText(RENAMED_TITLE);
  await expect(page.locator("header").getByText(RENAMED_TITLE)).toBeVisible();
  await expect(page).toHaveTitle(`${RENAMED_TITLE} - DeerFlow`);

  releaseStaleMetadataResponse();
  await staleMetadataResponseCompleted;
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );

  // The stale response has completed while the fresh refetch is still blocked.
  // The title must remain renamed without relying on the refetch to repair it.
  await expect(threadItem).toContainText(RENAMED_TITLE);
  await expect(page.locator("header").getByText(RENAMED_TITLE)).toBeVisible();
  await expect(page).toHaveTitle(`${RENAMED_TITLE} - DeerFlow`);

  await freshMetadataRequestStarted;
  releaseFreshMetadataResponse();
  await freshMetadataResponseCompleted;

  await expect(threadItem).toContainText(RENAMED_TITLE);
  await expect(page.locator("header").getByText(RENAMED_TITLE)).toBeVisible();
  await expect(page).toHaveTitle(`${RENAMED_TITLE} - DeerFlow`);
});
