import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// Issue #3482: the sidebar's "Recent chats" and the /workspace/chats list
// page used to stop at the first 50 threads with no way to load more.
// `useInfiniteThreads()` + a sentinel near the bottom of each list now
// pages through the backend.

const TOTAL_THREADS = 120;
const PAGE_SIZE = 50;

const THREADS = Array.from({ length: TOTAL_THREADS }, (_, i) => {
  // Pad index so titles sort deterministically as strings. Keep updated_at
  // monotonically descending to match the backend's updated_at-desc search
  // order, so paging boundaries are stable across runs.
  const index = String(i + 1).padStart(3, "0");
  return {
    thread_id: `00000000-0000-0000-0000-0000000${index.padStart(5, "0")}`,
    title: `Conversation ${index}`,
    updated_at: new Date(
      Date.UTC(2025, 5, 30, 12, 0, 0) - i * 60_000,
    ).toISOString(),
  };
});

const FIRST_PAGE_LAST = `Conversation ${String(PAGE_SIZE).padStart(3, "0")}`;
const SECOND_PAGE_FIRST = `Conversation ${String(PAGE_SIZE + 1).padStart(3, "0")}`;

// Side chats are hidden from the primary lists, so a page of 50 visible
// chats spans more server rows. Three side chats in the first 50 rows push
// the second page to server offset 53.
const SIDECAR_INDEXES = new Set([4, 21, 38]);
const THREADS_WITH_SIDE_CHATS = THREADS.map((thread, i) =>
  SIDECAR_INDEXES.has(i)
    ? {
        ...thread,
        metadata: {
          deerflow_sidecar: true,
          parent_thread_id: THREADS[0]!.thread_id,
        },
      }
    : thread,
);
const SECOND_PAGE_OFFSET = PAGE_SIZE + SIDECAR_INDEXES.size;

function observeSearchOffsets(page: Page) {
  const offsets: number[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /^\/api\/(?:langgraph\/)?threads\/search$/.test(
        new URL(request.url()).pathname,
      )
    ) {
      const body = request.postDataJSON() as { offset?: number } | null;
      offsets.push(body?.offset ?? 0);
    }
  });
  return offsets;
}

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
      // Archive-filtered lists use the Gateway directly; SDK callers keep
      // the LangGraph proxy path. Observe both search transports.
      if (
        request.method() === "POST" &&
        /^\/api\/(?:langgraph\/)?threads\/search$/.test(
          new URL(request.url()).pathname,
        )
      ) {
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
    expect(baselineRequests).toBeGreaterThan(0);

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
  test("sidebar loads the next page past hidden side chats after a rename", async ({
    page,
  }) => {
    const offsets = observeSearchOffsets(page);
    mockLangGraphAPI(page, { threads: THREADS_WITH_SIDE_CHATS });

    await page.goto("/workspace/chats/new");

    const lastVisibleOnFirstPage = `Conversation ${String(
      SECOND_PAGE_OFFSET,
    ).padStart(3, "0")}`;
    await expect(page.getByText(lastVisibleOnFirstPage).first()).toBeVisible({
      timeout: 15_000,
    });

    // Renaming rewrites the cached pages; the next page must still start
    // after the side chats the first page skipped.
    const firstItem = page
      .locator(
        `a[data-sidebar="menu-button"][href="/workspace/chats/${THREADS[0]!.thread_id}"]`,
      )
      .locator("xpath=..");
    await firstItem.hover();
    await firstItem.getByRole("button", { name: "More" }).click();
    await page.getByRole("menuitem", { name: "Rename" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox").fill("Renamed conversation");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog).toBeHidden();
    await expect(firstItem).toContainText("Renamed conversation");

    offsets.length = 0;
    await page
      .getByTestId("recent-chat-list-sentinel")
      .scrollIntoViewIfNeeded();

    const nextFirst = `Conversation ${String(SECOND_PAGE_OFFSET + 1).padStart(3, "0")}`;
    await expect(page.getByText(nextFirst).first()).toBeVisible({
      timeout: 15_000,
    });
    expect(offsets).toContain(SECOND_PAGE_OFFSET);
    expect(offsets).not.toContain(PAGE_SIZE);
  });
});
