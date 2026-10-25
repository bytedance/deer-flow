import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const recoveryEvent of ["online", "visibilitychange"] as const) {
  test(`authentication recovers after a network failure on ${recoveryEvent}`, async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.clock.install();
    let requests = 0;
    await page.route("**/api/v1/auth/me", async (route) => {
      requests++;
      if (requests === 1) {
        await route.abort("internetdisconnected");
        return;
      }
      await route.fulfill({
        json: {
          id: "default",
          email: "recovered@test.local",
          system_role: "admin",
          needs_setup: false,
          oauth_provider: null,
        },
      });
    });

    await page.goto("/workspace/chats/new?settings=account");
    const dialog = page.getByRole("dialog", { name: "Settings", exact: true });
    await expect(dialog.getByText("default@test.local")).toBeVisible();

    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await expect.poll(() => requests).toBe(1);
    await expect(dialog.getByText("default@test.local")).toBeHidden();
    await expect(page).not.toHaveURL(/\/login/);

    if (recoveryEvent === "visibilitychange") {
      await page.clock.fastForward(60_001);
    }
    await page.evaluate((event) => {
      if (event === "online") window.dispatchEvent(new Event(event));
      else document.dispatchEvent(new Event(event));
    }, recoveryEvent);

    await expect(dialog.getByText("recovered@test.local")).toBeVisible();
    expect(requests).toBe(2);
    await expect(page).not.toHaveURL(/\/login/);
  });
}
