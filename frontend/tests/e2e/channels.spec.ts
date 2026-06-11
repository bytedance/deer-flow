import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const channelProviders = [
  ["telegram", "Telegram", "deep_link"],
  ["slack", "Slack", "binding_code"],
  ["discord", "Discord", "binding_code"],
  ["feishu", "Feishu", "binding_code"],
  ["dingtalk", "DingTalk", "binding_code"],
  ["wechat", "WeChat", "binding_code"],
  ["wecom", "WeCom", "binding_code"],
] as const;

type MockChannelProvider = {
  provider: string;
  display_name: string;
  enabled: boolean;
  configured: boolean;
  connectable: boolean;
  auth_mode: string;
  connection_status: string;
  unavailable_reason?: string | null;
};

function defaultProviders(): MockChannelProvider[] {
  return channelProviders.map(([provider, displayName, authMode]) => ({
    provider,
    display_name: displayName,
    enabled: true,
    configured: true,
    connectable: true,
    auth_mode: authMode,
    connection_status: "not_connected",
  }));
}

function mockChannelsAPI(
  page: Page,
  providers: MockChannelProvider[] = defaultProviders(),
  onSlackConnect?: () => void,
) {
  void page.route("**/api/channels/providers", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        providers,
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
    onSlackConnect?.();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provider: "slack",
        mode: "binding_code",
        url: null,
        code: "abc123",
        instruction: "Send /connect abc123 to the DeerFlow Slack bot.",
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
    await expect(sidebar.getByText("Feishu")).toBeVisible();
    await expect(sidebar.getByText("DingTalk")).toBeVisible();
    await expect(sidebar.getByText("WeChat")).toBeVisible();
    await expect(sidebar.getByText("WeCom")).toBeVisible();
    await expect(sidebar.getByRole("button", { name: "Connect" })).toHaveCount(
      7,
    );

    await sidebar.getByRole("button", { name: /Settings and more/ }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Channels" }).click();

    await expect(page.getByText("Telegram direct messages")).toBeVisible();
    await expect(page.getByText("Slack workspace messages")).toBeVisible();
    await expect(page.getByText("Discord server messages")).toBeVisible();
    await expect(page.getByText("Feishu and Lark messages")).toBeVisible();
    await expect(page.getByText("DingTalk Stream Push messages")).toBeVisible();
    await expect(page.getByText("WeChat iLink messages")).toBeVisible();
    await expect(page.getByText("WeCom messages")).toBeVisible();

    const dialog = page.getByRole("dialog", { name: "Settings" });
    const connectButtons = dialog.getByRole("button", { name: "Connect" });
    await expect(connectButtons).toHaveCount(7);

    await connectButtons.nth(1).click();
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);
    await expect(
      page.getByText("Send /connect abc123 to the DeerFlow Slack bot."),
    ).toBeVisible();
  });

  test("unavailable providers stay clickable and explain what is missing", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    const unavailableReason =
      "Enable and configure channels.slack with channels.slack.bot_token and channels.slack.app_token.";
    let connectRequests = 0;
    mockChannelsAPI(
      page,
      [
        {
          provider: "slack",
          display_name: "Slack",
          enabled: true,
          configured: false,
          connectable: false,
          unavailable_reason: unavailableReason,
          auth_mode: "binding_code",
          connection_status: "not_connected",
        },
      ],
      () => {
        connectRequests += 1;
      },
    );

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const connectButton = sidebar.getByRole("button", { name: "Connect" });
    await expect(connectButton).toBeEnabled({ timeout: 15_000 });

    await connectButton.click();

    await expect(page.getByText(unavailableReason)).toBeVisible();
    expect(connectRequests).toBe(0);
  });
});
