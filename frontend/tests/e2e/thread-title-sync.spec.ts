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
