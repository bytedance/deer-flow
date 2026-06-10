import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, type MockThread } from "./utils/mock-api";

// More than one page (page size is 50) so the lists must load incrementally
// to reach the oldest conversations. Regression cover for #3482, where the
// thread list was hard-capped at the most recent 50 with no way to load more.
const TOTAL_THREADS = 120;

function makeThreads(count: number): MockThread[] {
  return Array.from({ length: count }, (_, i) => {
    const n = i + 1;
    return {
      thread_id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`,
      // Newest first: index 0 is the most recently updated.
      title: `Conversation ${String(n).padStart(3, "0")}`,
      updated_at: "2025-01-01T00:00:00Z",
    };
  });
}

test.describe("Thread list pagination (#3482)", () => {
  test("chats page loads older threads as the list is scrolled", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: makeThreads(TOTAL_THREADS) });

    await page.goto("/workspace/chats");

    const list = page.locator("[data-slot='scroll-area-viewport']");
    const firstThread = list.getByText("Conversation 001", { exact: true });
    const lastThread = list.getByText("Conversation 120", { exact: true });

    // First page is rendered, the tail of the list is not loaded yet.
    await expect(firstThread).toBeVisible({ timeout: 15_000 });
    await expect(lastThread).toHaveCount(0);

    // Scrolling to the bottom should keep pulling pages until the list ends.
    await expect
      .poll(
        async () => {
          await list.evaluate((el) => el.scrollTo(0, el.scrollHeight));
          return lastThread.count();
        },
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);

    // A thread well past the original 50-item cap is now reachable.
    await expect(list.getByText("Conversation 051", { exact: true })).toHaveCount(
      1,
    );
    await expect(lastThread).toHaveCount(1);
  });

  test("sidebar recent chats auto-load past the first page on scroll", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: makeThreads(TOTAL_THREADS) });

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const content = sidebar.locator("[data-sidebar='content']");
    const lastThread = sidebar.getByText("Conversation 120", { exact: true });

    await expect(
      sidebar.getByText("Conversation 001", { exact: true }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(lastThread).toHaveCount(0);

    // Scrolling the recent-chats panel to the bottom auto-loads the next page,
    // which is exactly the interaction the bug report asks for.
    await expect
      .poll(
        async () => {
          await content.evaluate((el) => el.scrollTo(0, el.scrollHeight));
          return lastThread.count();
        },
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);

    await expect(lastThread).toHaveCount(1);
    await expect(
      sidebar.getByRole("button", { name: "Load more" }),
    ).toHaveCount(0);
  });
});
