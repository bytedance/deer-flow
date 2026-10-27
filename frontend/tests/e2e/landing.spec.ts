import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Enterprise entry", () => {
  test("redirects the root to account login without rendering the landing page", async ({
    request,
  }) => {
    const response = await request.get("/", { maxRedirects: 0 });
    expect(response.status()).toBe(307);
    expect(response.headers().location).toBe("/login");
  });

  // The standard E2E server disables authentication and supplies a signed-in user.
  test("continues into the workspace when authentication is already satisfied", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    await page.goto("/");
    await page.waitForURL("**/workspace/chats/new");
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);
  });
});
