import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const CHAT = "00000000-0000-0000-0000-000000000901";
const TITLE = "Report to keep";

async function openDeleteDialog(page: Page, captureEntry = false) {
  const link = page.locator(
    `a[data-sidebar="menu-button"][href="/workspace/chats/${CHAT}"]`,
  );
  await link.hover();
  await link.locator("xpath=..").getByRole("button", { name: "More" }).click();
  if (captureEntry) {
    await page.screenshot({
      path: test.info().outputPath("delete-entry-point.png"),
      animations: "disabled",
    });
  }
  await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
  return page.getByRole("dialog", { name: "Delete chat", exact: true });
}

test("opening and dismissing deletion never sends a delete request", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [{ thread_id: CHAT, title: TITLE }] });
  const deletes: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "DELETE") deletes.push(request.url());
  });
  await page.goto(`/workspace/chats/${CHAT}`);
  for (const dismissal of ["Cancel", "Escape", "Close"]) {
    const dialog = await openDeleteDialog(page);
    await expect(dialog).toContainText(TITLE);
    await expect(dialog).toContainText("cannot be undone");
    await expect(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeFocused();
    expect(deletes).toEqual([]);
    if (dismissal === "Escape") await page.keyboard.press("Escape");
    else
      await dialog
        .getByRole("button", { name: dismissal, exact: true })
        .click();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(new RegExp(CHAT));
    expect(deletes).toEqual([]);
  }
});

test("confirmation waits for deletion, prevents dismissal, and permits retry after failure", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, { threads: [{ thread_id: CHAT, title: TITLE }] });
  let releaseDelete!: () => void;
  const gate = new Promise<void>((resolve) => {
    releaseDelete = resolve;
  });
  let attempts = 0;
  await page.route(`**/api/langgraph/threads/${CHAT}`, async (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    attempts++;
    if (attempts > 1) return route.fallback();
    await gate;
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Permission denied" }),
    });
  });
  await page.goto(`/workspace/chats/${CHAT}`);
  const dialog = await openDeleteDialog(page, true);
  await expect(page.getByRole("menu")).toBeHidden();
  await page.screenshot({
    path: testInfo.outputPath("delete-confirm.png"),
    animations: "disabled",
  });
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(() => attempts).toBe(1);
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeDisabled();
  await expect(
    dialog.getByRole("button", { name: "Loading", exact: false }),
  ).toBeDisabled();
  await expect(
    dialog.getByRole("button", { name: "Close", exact: true }),
  ).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.mouse.click(5, 5);
  await expect(dialog).toBeVisible();
  expect(attempts).toBe(1);
  releaseDelete();
  await expect.soft(page.getByText(/Permission denied/)).toBeVisible();
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await page.screenshot({
    path: testInfo.outputPath("delete-error.png"),
    animations: "disabled",
  });
  await expect(page).toHaveURL(new RegExp(CHAT));
  await page.keyboard.press("Tab");
  await expect(
    dialog.getByRole("button", { name: "Delete", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
  await expect(
    page.locator(
      `a[data-sidebar="menu-button"][href="/workspace/chats/${CHAT}"]`,
    ),
  ).toHaveCount(0);
  expect(attempts).toBe(2);
});

for (const active of [true, false]) {
  test(`cleanup failure keeps ${active ? "active" : "inactive"} chat deletion retryable after the row disappears`, async ({
    page,
  }) => {
    const other = "00000000-0000-0000-0000-000000000902";
    mockLangGraphAPI(page, {
      threads: [
        { thread_id: CHAT, title: TITLE },
        { thread_id: other, title: "Keep open" },
      ],
    });
    let releaseCleanup!: () => void;
    const cleanupGate = new Promise<void>((resolve) => {
      releaseCleanup = resolve;
    });
    let remoteAttempts = 0;
    let cleanupAttempts = 0;
    await page.route(`**/api/langgraph/threads/${CHAT}`, (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      remoteAttempts++;
      // The real gateway has require_existing=True: after the first successful
      // deletion, a retry must accept 404 and continue with local cleanup.
      if (remoteAttempts > 1)
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Thread not found" }),
        });
      return route.fallback();
    });
    await page.route(`**/api/threads/${CHAT}`, async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      cleanupAttempts++;
      if (cleanupAttempts > 1) return route.fallback();
      await cleanupGate;
      return route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Cleanup failed" }),
      });
    });
    const originalPath = `/workspace/chats/${active ? CHAT : other}`;
    await page.goto(originalPath);
    const dialog = await openDeleteDialog(page);
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect.poll(() => cleanupAttempts).toBe(1);
    await expect(page).toHaveURL(new RegExp(`${originalPath}$`));
    await expect(dialog).toBeVisible();
    releaseCleanup();
    await expect(
      page.getByText("Cleanup failed", { exact: true }),
    ).toBeVisible();
    // onSettled refetches the list, which no longer contains this thread.
    await expect(
      page.locator(
        `a[data-sidebar="menu-button"][href="/workspace/chats/${CHAT}"]`,
      ),
    ).toHaveCount(0);
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(TITLE);
    await expect(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeFocused();
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect.poll(() => cleanupAttempts).toBe(2);
    expect(remoteAttempts).toBe(2);
    await expect(page).toHaveURL(
      active ? /\/workspace\/chats\/new$/ : new RegExp(`${originalPath}$`),
    );
  });
}
