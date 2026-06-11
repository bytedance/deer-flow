import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// Issue #3482: the sidebar's "Recent chats" and the /workspace/chats list
// page used to stop at the first 50 threads with no way to load more.
// `useInfiniteThreads()` + a sentinel near the bottom of each list now
// pages through the backend.

const TOTAL_THREADS = 120;
const PAGE_SIZE = 50;

const THREADS = Array.from({ length: TOTAL_THREADS }, (_, i) => {
  // Pad index so titles sort deterministically as strings. The thread-search
  // mock returns threads in the order provided, so paging boundaries are
  // stable across runs.
  const index = String(i + 1).padStart(3, "0");
  return {
    thread_id: `00000000-0000-0000-0000-0000000${index.padStart(5, "0")}`,
    title: `Conversation ${index}`,
    updated_at: `2025-06-${String((i % 28) + 1).padStart(2, "0")}T12:00:00Z`,
  };
});

const FIRST_PAGE_LAST = `Conversation ${String(PAGE_SIZE).padStart(3, "0")}`;
const SECOND_PAGE_FIRST = `Conversation ${String(PAGE_SIZE + 1).padStart(3, "0")}`;

test.describe("Thread list infinite scroll (issue #3482)", () => {
  test("chats list page loads more threads when scrolling to the bottom", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats");

    const main = page.locator("main");

    // First page renders.
    await expect(main.getByText(FIRST_PAGE_LAST)).toBeVisible({
      timeout: 15_000,
    });
    // Items past the first page have not been fetched yet.
    await expect(main.getByText(SECOND_PAGE_FIRST)).toHaveCount(0);

    // Scrolling the sentinel into view triggers the next page.
    const sentinel = page.getByTestId("chats-page-sentinel");
    await sentinel.scrollIntoViewIfNeeded();

    await expect(main.getByText(SECOND_PAGE_FIRST)).toBeVisible({
      timeout: 15_000,
    });
  });

  test("sidebar recent chats loads more threads when scrolling to the bottom", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats/new");

    // The 50th thread (end of first page) appears in the sidebar.
    await expect(page.getByText(FIRST_PAGE_LAST).first()).toBeVisible({
      timeout: 15_000,
    });
    // The 51st has not been fetched yet.
    await expect(page.getByText(SECOND_PAGE_FIRST)).toHaveCount(0);

    // Scroll the sidebar sentinel into view to trigger the next page.
    const sentinel = page.getByTestId("recent-chat-list-sentinel");
    await sentinel.scrollIntoViewIfNeeded();

    await expect(page.getByText(SECOND_PAGE_FIRST).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("chats list page does NOT auto-paginate while a search filter is active", async ({
    page,
  }) => {
    // Count search requests via a passive request observer.  Using
    // page.route() here would race with mockLangGraphAPI's fulfill route
    // (Playwright matches routes in reverse registration order), so the
    // counter could miss real requests.  page.on('request') is a pure
    // observer and never interferes with routing.
    let searchRequestCount = 0;
    page.on("request", (request) => {
      if (request.url().includes("/api/langgraph/threads/search")) {
        searchRequestCount += 1;
      }
    });

    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats");

    // Wait for the first page to render so we have a baseline count.
    await expect(page.locator("main").getByText(FIRST_PAGE_LAST)).toBeVisible({
      timeout: 15_000,
    });
    const baselineRequests = searchRequestCount;

    // Type a query that matches nothing in the first page (and nothing at
    // all, since titles are deterministic).
    await page
      .getByPlaceholder("Search chats")
      .fill("zzz-no-such-conversation");

    // The auto-sentinel must be gone; an explicit button takes its place.
    await expect(page.getByTestId("chats-page-sentinel")).toHaveCount(0);
    await expect(page.getByTestId("chats-page-load-more")).toBeVisible();

    // Give the IntersectionObserver a couple of frames to misbehave if the
    // guard regresses.  No additional /threads/search calls should fire.
    await page.waitForTimeout(500);
    expect(searchRequestCount).toBe(baselineRequests);

    // The explicit button still works as an escape hatch.
    await page.getByTestId("chats-page-load-more").click();
    await expect
      .poll(() => searchRequestCount, { timeout: 10_000 })
      .toBeGreaterThan(baselineRequests);
  });
});
