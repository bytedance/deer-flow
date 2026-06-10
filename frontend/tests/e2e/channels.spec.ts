import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

function mockChannelsAPI(page: Page) {
  void page.route("**/api/channels/providers", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        providers: [
          {
            provider: "telegram",
            display_name: "Telegram",
            enabled: true,
            configured: true,
            auth_mode: "deep_link",
            connection_status: "not_connected",
          },
          {
            provider: "slack",
            display_name: "Slack",
            enabled: true,
            configured: true,
            auth_mode: "oauth",
            connection_status: "not_connected",
          },
          {
            provider: "discord",
            display_name: "Discord",
            enabled: true,
            configured: true,
            auth_mode: "oauth_and_bot_install",
            connection_status: "not_connected",
          },
        ],
      }),
    });
  });

  void page.route("**/api/channels/connections", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ connections: [] }),
    });
  });

  void page.route("**/api/channels/slack/connect", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provider: "slack",
        mode: "oauth",
        url: "http://localhost:3000/mock-slack-oauth?client_id=dev&state=test",
        expires_in: 600,
      }),
    });
  });
}

test.describe("IM channels", () => {
  test("sidebar and settings expose channel connections", async ({ page }) => {
    mockLangGraphAPI(page);
    mockChannelsAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Channels")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.getByText("Telegram")).toBeVisible();
    await expect(sidebar.getByText("Slack")).toBeVisible();
    await expect(sidebar.getByText("Discord")).toBeVisible();
    await expect(sidebar.getByRole("button", { name: "Connect" })).toHaveCount(
      3,
    );

    await sidebar.getByRole("button", { name: /Settings and more/ }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Channels" }).click();

    await expect(page.getByText("Telegram direct messages")).toBeVisible();
    await expect(page.getByText("Slack workspace messages")).toBeVisible();
    await expect(page.getByText("Discord server messages")).toBeVisible();

    const dialog = page.getByRole("dialog", { name: "Settings" });
    const connectButtons = dialog.getByRole("button", { name: "Connect" });
    await expect(connectButtons).toHaveCount(3);

    const popupPromise = page.waitForEvent("popup");
    await connectButtons.nth(1).click();
    const popup = await popupPromise;
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);
    await expect(popup).toHaveURL(/\/mock-slack-oauth/);
    await popup.close();
  });
});
