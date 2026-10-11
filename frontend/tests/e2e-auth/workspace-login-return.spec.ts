import { expect, test } from "@playwright/test";

/**
 * A workspace page opened without a session — an expired cookie, or a
 * notification link opened later — must come back to the same page, query
 * string included, after the user signs in. The workspace layout cannot read
 * the request URL on the server, so the bounce happens in the browser.
 */
test.describe("workspace login bounce", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/auth/providers", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ providers: [] }),
      }),
    );
    await page.route("**/api/v1/auth/setup-status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ needs_setup: false }),
      }),
    );
  });

  test("keeps the deep link's query string in next", async ({ page }) => {
    await page.goto("/workspace/scheduled-tasks?task_id=task-1");

    await expect(page).toHaveURL(
      "/login?next=%2Fworkspace%2Fscheduled-tasks%3Ftask_id%3Dtask-1",
    );
    await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible();
  });

  test("keeps a nested workspace path in next", async ({ page }) => {
    await page.goto("/workspace/chats/thread-1");

    await expect(page).toHaveURL("/login?next=%2Fworkspace%2Fchats%2Fthread-1");
  });

  test("keeps the fragment in next", async ({ page }) => {
    // The server never sees the fragment; only the browser bounce can keep it.
    await page.goto("/workspace/chats/thread-1#message-3");

    await expect(page).toHaveURL(
      "/login?next=%2Fworkspace%2Fchats%2Fthread-1%23message-3",
    );
  });

  test("does not mount workspace pages before the bounce", async ({ page }) => {
    // The layout renders only the redirect, so the chat page under it must
    // never start loading data for a visitor without a session.
    const workspaceRequests: string[] = [];
    page.on("request", (request) => {
      const { pathname } = new URL(request.url());
      if (
        pathname.startsWith("/api/") &&
        !pathname.startsWith("/api/v1/auth/")
      ) {
        workspaceRequests.push(pathname);
      }
    });

    await page.goto("/workspace/chats/thread-1");
    await expect(page).toHaveURL(/\/login\?next=/);
    await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible();

    expect(workspaceRequests).toEqual([]);
  });

  test("does not leave the bounce page in history", async ({ page }) => {
    await page.goto("/login");
    await page.goto("/workspace/scheduled-tasks?task_id=task-1");
    await expect(page).toHaveURL(/\/login\?next=/);

    await page.goBack();

    await expect(page).toHaveURL("/login");
  });
});
