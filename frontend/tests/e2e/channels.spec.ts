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
  credential_fields?: Array<{
    name: string;
    label: string;
    type: string;
    required: boolean;
  }>;
  credential_values?: Record<string, string>;
};

function defaultProviders(): MockChannelProvider[] {
  return channelProviders.map(([provider, displayName, authMode]) => ({
    provider,
    display_name: displayName,
    enabled: true,
    configured: true,
    connectable: true,
    auth_mode: authMode,
    connection_status: "connected",
    credential_fields: [
      {
        name: "token",
        label: "Token",
        type: "password",
        required: true,
      },
    ],
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
    await expect(
      sidebar.getByRole("button", { name: "Connected" }),
    ).toHaveCount(7);

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
    await expect(dialog.getByRole("button", { name: "Modify" })).toHaveCount(7);
  });

  test("only enabled providers are shown and runtime setup stays editable", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let slackConfigured = false;
    let submittedValues: Record<string, string> | undefined;

    void page.route("**/api/channels/providers", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          providers: [
            {
              provider: "slack",
              display_name: "Slack",
              enabled: true,
              configured: slackConfigured,
              connectable: slackConfigured,
              auth_mode: "binding_code",
              connection_status: slackConfigured
                ? "connected"
                : "not_connected",
              credential_fields: [
                {
                  name: "bot_token",
                  label: "Bot token",
                  type: "password",
                  required: true,
                },
                {
                  name: "app_token",
                  label: "App token",
                  type: "password",
                  required: true,
                },
              ],
              credential_values: slackConfigured
                ? {
                    bot_token: "********",
                    app_token: "********",
                  }
                : {},
            },
            {
              provider: "discord",
              display_name: "Discord",
              enabled: false,
              configured: false,
              connectable: false,
              auth_mode: "binding_code",
              connection_status: "not_connected",
              credential_fields: [],
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

    void page.route("**/api/channels/slack/runtime-config", async (route) => {
      const body = route.request().postDataJSON() as {
        values: Record<string, string>;
      };
      submittedValues = body.values;
      slackConfigured = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider: "slack",
          display_name: "Slack",
          enabled: true,
          configured: true,
          connectable: true,
          auth_mode: "binding_code",
          connection_status: "connected",
          credential_fields: [],
          credential_values: {},
        }),
      });
    });

    void page.route("**/api/channels/slack/connect", (route) => route.abort());

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Slack")).toBeVisible({ timeout: 15_000 });
    await expect(sidebar.getByText("Discord")).toBeHidden();
    const connectButton = sidebar.getByRole("button", { name: "Connect" });
    await expect(connectButton).toBeEnabled();

    await connectButton.click();

    const setupDialog = page.getByRole("dialog", { name: "Connect Slack" });
    await expect(setupDialog).toBeVisible();
    const botTokenInput = setupDialog.getByLabel("Bot token");
    await expect(botTokenInput).toHaveAttribute("type", "text");
    await expect(botTokenInput).toHaveAttribute("autocomplete", "off");
    await expect(botTokenInput).toHaveAttribute("data-lpignore", "true");
    await expect(botTokenInput).toHaveAttribute("data-1p-ignore", "true");
    await expect(botTokenInput).toHaveCSS("-webkit-text-security", "disc");
    await setupDialog.getByLabel("Bot token").fill("xoxb-ui");
    await setupDialog.getByLabel("App token").fill("xapp-ui");
    await setupDialog.getByRole("button", { name: "Save and connect" }).click();

    await expect(setupDialog).toBeHidden();
    await expect(
      sidebar.getByRole("button", { name: "Connected" }),
    ).toBeVisible();
    await sidebar.getByRole("button", { name: "Connected" }).click();
    await expect(
      page.getByRole("dialog", { name: "Modify Slack" }),
    ).toBeVisible();
    await expect(page.getByLabel("Bot token")).toHaveValue("********");
    await expect(page.getByLabel("App token")).toHaveValue("********");
    expect(submittedValues).toEqual({
      bot_token: "xoxb-ui",
      app_token: "xapp-ui",
    });
  });

  test("configured provider connects directly with a binding-code instruction", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let slackConnectCalls = 0;
    mockChannelsAPI(
      page,
      [
        {
          provider: "slack",
          display_name: "Slack",
          enabled: true,
          configured: true,
          connectable: true,
          auth_mode: "binding_code",
          connection_status: "not_connected",
          credential_fields: [
            {
              name: "bot_token",
              label: "Bot token",
              type: "password",
              required: true,
            },
          ],
          credential_values: { bot_token: "********" },
        },
      ],
      () => {
        slackConnectCalls += 1;
      },
    );

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Slack")).toBeVisible({ timeout: 15_000 });
    await sidebar.getByRole("button", { name: "Connect" }).click();

    await expect(
      page.getByText("Send /connect abc123 to the DeerFlow Slack bot."),
    ).toBeVisible();
    expect(slackConnectCalls).toBe(1);
  });

  test("runtime setup continues into the connect flow when a binding is still required", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let slackConfigured = false;
    let slackConnectCalls = 0;

    void page.route("**/api/channels/providers", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          providers: [
            {
              provider: "slack",
              display_name: "Slack",
              enabled: true,
              configured: slackConfigured,
              connectable: slackConfigured,
              auth_mode: "binding_code",
              connection_status: "not_connected",
              credential_fields: [
                {
                  name: "bot_token",
                  label: "Bot token",
                  type: "password",
                  required: true,
                },
              ],
              credential_values: {},
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

    void page.route("**/api/channels/slack/runtime-config", (route) => {
      slackConfigured = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider: "slack",
          display_name: "Slack",
          enabled: true,
          configured: true,
          connectable: true,
          auth_mode: "binding_code",
          connection_status: "not_connected",
          credential_fields: [],
          credential_values: {},
        }),
      });
    });

    void page.route("**/api/channels/slack/connect", (route) => {
      slackConnectCalls += 1;
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

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Slack")).toBeVisible({ timeout: 15_000 });
    await sidebar.getByRole("button", { name: "Connect" }).click();

    const setupDialog = page.getByRole("dialog", { name: "Connect Slack" });
    await expect(setupDialog).toBeVisible();
    await setupDialog.getByLabel("Bot token").fill("xoxb-ui");
    await setupDialog.getByRole("button", { name: "Save and connect" }).click();

    await expect(setupDialog).toBeHidden();
    await expect(
      page.getByText("Send /connect abc123 to the DeerFlow Slack bot."),
    ).toBeVisible();
    expect(slackConnectCalls).toBe(1);
  });

  test("runtime setup dialog prefills editable credential values", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockChannelsAPI(page, [
      {
        provider: "feishu",
        display_name: "Feishu",
        enabled: true,
        configured: true,
        connectable: true,
        auth_mode: "binding_code",
        connection_status: "connected",
        credential_fields: [
          {
            name: "app_id",
            label: "App ID",
            type: "text",
            required: true,
          },
          {
            name: "app_secret",
            label: "App secret",
            type: "password",
            required: true,
          },
        ],
        credential_values: {
          app_id: "cli_feishu_app",
          app_secret: "********",
        },
      },
    ]);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Feishu")).toBeVisible({ timeout: 15_000 });
    await sidebar.getByRole("button", { name: "Connected" }).click();

    const setupDialog = page.getByRole("dialog", { name: "Modify Feishu" });
    await expect(setupDialog).toBeVisible();
    await expect(setupDialog.getByLabel("App ID")).toHaveValue(
      "cli_feishu_app",
    );
    await expect(setupDialog.getByLabel("App secret")).toHaveValue("********");
  });
});
