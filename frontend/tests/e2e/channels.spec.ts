import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const channelProviders = [
  ["buzz", "Buzz", "binding_code"],
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
    await expect(sidebar.getByText("Buzz")).toBeVisible();
    await expect(sidebar.getByText("Telegram")).toBeVisible();
    await expect(sidebar.getByText("Slack")).toBeVisible();
    await expect(sidebar.getByText("Discord")).toBeVisible();
    await expect(sidebar.getByText("Feishu")).toBeVisible();
    await expect(sidebar.getByText("DingTalk")).toBeVisible();
    await expect(sidebar.getByText("WeChat")).toBeVisible();
    await expect(sidebar.getByText("WeCom")).toBeVisible();
    await expect(
      sidebar.getByRole("button", { name: "Connected" }),
    ).toHaveCount(8);

    await sidebar.getByRole("button", { name: /Settings and more/ }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Channels" }).click();

    await expect(
      page.getByText("Buzz channels and direct messages"),
    ).toBeVisible();
    await expect(page.getByText("Telegram direct messages")).toBeVisible();
    await expect(page.getByText("Slack workspace messages")).toBeVisible();
    await expect(page.getByText("Discord server messages")).toBeVisible();
    await expect(page.getByText("Feishu and Lark messages")).toBeVisible();
    await expect(page.getByText("DingTalk Stream Push messages")).toBeVisible();
    await expect(page.getByText("WeChat iLink messages")).toBeVisible();
    await expect(page.getByText("WeCom messages")).toBeVisible();

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog.getByRole("button", { name: "Modify" })).toHaveCount(8);
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

test("WeChat QR setup keeps account binding separate and supports manual entry", async ({
  page,
}, testInfo) => {
  const hydrationErrors: string[] = [];
  page.on("console", (message) => {
    if (
      /hydration|hydrated|server rendered HTML|Minified React error #(418|423|425)/i.test(
        message.text(),
      )
    )
      hydrationErrors.push(message.text());
  });
  mockLangGraphAPI(page);
  const wechat: MockChannelProvider = {
    provider: "wechat",
    display_name: "WeChat",
    enabled: true,
    configured: false,
    connectable: false,
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
  };
  mockChannelsAPI(page, [wechat]);
  let confirm = false;
  let cancelled = 0;
  let connected = 0;
  let bound = false;
  await page.route("**/api/channels/connections", (route) =>
    route.fulfill({
      json: {
        connections: bound
          ? [{ id: "wechat-binding", provider: "wechat", status: "connected" }]
          : [],
      },
    }),
  );
  let starts = 0;
  let session = {
    id: "preview-session",
    status: "pending",
    qrcode_content: "https://example.com/wechat-demo",
    expires_in: 180,
    provider: null,
  };
  await page.route("**/api/channels/wechat/qr-login", (route) => {
    starts += 1;
    session = {
      ...session,
      id: `preview-session-${starts}`,
      qrcode_content: `https://example.com/wechat-demo?attempt=${starts}`,
    };
    return route.fulfill({ json: session });
  });
  await page.route("**/api/channels/wechat/qr-login/*/poll", (route) =>
    route.fulfill({
      json: confirm
        ? {
            ...session,
            status: "confirmed",
            provider: {
              ...wechat,
              configured: true,
              connectable: true,
              credential_values: { bot_token: "********" },
            },
          }
        : session,
    }),
  );
  await page.route("**/api/channels/wechat/qr-login/*", (route) => {
    cancelled += 1;
    return route.fulfill({ status: 204 });
  });
  await page.route("**/api/channels/wechat/connect", (route) => {
    connected += 1;
    return route.fulfill({
      json: {
        provider: "wechat",
        mode: "binding_code",
        code: "demo-code",
        instruction: "Send /connect demo-code to the WeChat bot.",
        expires_in: 600,
      },
    });
  });

  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: "Connect", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("img", { name: "WeChat login QR code" }),
  ).toBeAttached();
  await expect(
    dialog.getByText("Scan this code with WeChat, then confirm on your phone."),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("wechat-qr-preview.png"),
    animations: "disabled",
  });
  const cancellationsBeforeSwitch = cancelled;
  await dialog.getByRole("tab", { name: "Use token" }).click();
  await expect(dialog.getByLabel("Bot token")).toBeVisible();
  await dialog.getByLabel("Bot token").fill("example-token");
  await page.screenshot({
    path: testInfo.outputPath("wechat-token-preview.png"),
    animations: "disabled",
  });
  await expect.poll(() => cancelled).toBeGreaterThan(cancellationsBeforeSwitch);
  await dialog.getByRole("tab", { name: "Scan QR code" }).click();
  await expect(
    dialog.getByRole("img", { name: "WeChat login QR code" }),
  ).toBeAttached();
  await dialog.getByRole("tab", { name: "Use token" }).click();
  await expect(dialog.getByLabel("Bot token")).toHaveValue("example-token");
  await dialog.getByRole("tab", { name: "Scan QR code" }).click();
  confirm = true;
  await expect(dialog.getByText("Token saved securely")).toBeVisible({
    timeout: 10_000,
  });
  await expect.poll(() => connected).toBe(1);
  await expect(
    dialog.getByText("/connect demo-code", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Copy command" }),
  ).toBeVisible();
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await dialog.getByRole("button", { name: "Copy command" }).click();
  await expect(
    dialog.getByRole("button", { name: "Copied", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "/connect demo-code",
  );
  await page.screenshot({
    path: testInfo.outputPath("wechat-binding-preview.png"),
    animations: "disabled",
  });
  // Moving the command to the phone can take the user out of the bot screen.
  // Rescanning must recover in-place and keep that already-copied command.
  const startsBeforeRetry = starts;
  confirm = false;
  await dialog.getByRole("button", { name: "Scan again", exact: true }).click();
  await expect(
    dialog.getByRole("img", { name: "WeChat login QR code" }),
  ).toBeVisible();
  await expect.poll(() => starts).toBe(startsBeforeRetry + 1);
  await expect(
    dialog.getByText("/connect demo-code", { exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("tab", { name: "Scan QR code" }),
  ).toHaveAttribute("aria-selected", "true");
  confirm = true;
  await expect(
    dialog.getByText("/connect demo-code", { exact: true }),
  ).toBeVisible();
  expect(connected).toBe(1);
  bound = true;
  await expect(dialog.getByText("WeChat is connected")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("wechat-connected-preview.png"),
    animations: "disabled",
  });
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(hydrationErrors).toEqual([]);
});

test("WeChat phone pairing code leads to persistent connection success", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page);
  const wechat: MockChannelProvider = {
    provider: "wechat",
    display_name: "WeChat",
    enabled: true,
    configured: false,
    connectable: false,
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
  };
  mockChannelsAPI(page, [wechat]);
  const session = {
    id: "pairing-session",
    status: "pending",
    qrcode_content: "https://example.com/scan",
    expires_in: 180,
    provider: null,
  };
  let starts = 0;
  let submitted = "";
  await page.route("**/api/channels/wechat/qr-login", (route) => {
    starts += 1;
    return route.fulfill({ json: session });
  });
  await page.route(
    "**/api/channels/wechat/qr-login/pairing-session/poll",
    (route) => {
      const body = route.request().postDataJSON() as {
        verify_code?: string;
      } | null;
      submitted = body?.verify_code ?? "";
      return route.fulfill({
        json:
          submitted === "123456"
            ? {
                ...session,
                status: "confirmed",
                provider: {
                  ...wechat,
                  configured: true,
                  connection_status: "connected",
                },
              }
            : { ...session, status: "verification_required" },
      });
    },
  );
  await page.route("**/api/channels/wechat/qr-login/pairing-session", (route) =>
    route.fulfill({ status: 204 }),
  );
  await page.goto("/workspace/chats/new");
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: "Connect", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Pairing code")).toBeVisible();
  expect(starts).toBe(1);
  await dialog.getByLabel("Pairing code").fill("123456");
  await page.screenshot({
    path: testInfo.outputPath("wechat-pairing-preview.png"),
    animations: "disabled",
  });
  await dialog.getByRole("button", { name: "Continue connecting" }).click();
  await expect(dialog.getByText("Token saved securely")).toBeVisible();
  await expect(dialog.getByText("WeChat is connected")).toBeVisible();
  expect(submitted).toBe("123456");
  await expect(dialog.getByRole("tab")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(dialog).not.toBeVisible();
});

for (const entry of ["sidebar", "settings"] as const) {
  for (const flow of ["existing token", "manual token"] as const) {
    test(`WeChat ${flow} from ${entry} keeps binding and QR recovery in a dialog`, async ({
      page,
    }) => {
      mockLangGraphAPI(page);
      const wechat: MockChannelProvider = {
        provider: "wechat",
        display_name: "WeChat",
        enabled: true,
        configured: flow === "existing token",
        connectable: flow === "existing token",
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
        credential_values:
          flow === "existing token" ? { bot_token: "********" } : {},
      };
      mockChannelsAPI(page, [wechat]);
      let bindingCalls = 0;
      let qrStarts = 0;
      await page.route("**/api/channels/wechat/connect", (route) => {
        bindingCalls += 1;
        return route.fulfill({
          json: {
            provider: "wechat",
            mode: "binding_code",
            code: "recovery-demo",
            instruction:
              "Send /connect recovery-demo to the DeerFlow WeChat bot.",
            expires_in: 600,
          },
        });
      });
      await page.route("**/api/channels/wechat/runtime-config", (route) => {
        expect(route.request().method()).toBe("POST");
        wechat.configured = true;
        wechat.connectable = true;
        wechat.credential_values = { bot_token: "********" };
        return route.fulfill({ json: wechat });
      });
      const session = {
        id: "recovery-session",
        status: "pending",
        qrcode_content: "https://example.com/recovery",
        expires_in: 180,
        provider: null,
      };
      await page.route("**/api/channels/wechat/qr-login", (route) => {
        qrStarts += 1;
        return route.fulfill({ json: session });
      });
      await page.route(
        "**/api/channels/wechat/qr-login/recovery-session/poll",
        (route) => route.fulfill({ json: session }),
      );
      await page.route(
        "**/api/channels/wechat/qr-login/recovery-session",
        (route) => route.fulfill({ status: 204 }),
      );
      await page.goto("/workspace/chats/new");
      const sidebar = page.locator("[data-sidebar='sidebar']");
      if (entry === "settings") {
        await sidebar
          .getByRole("button", { name: /Settings and more/ })
          .click();
        await page.getByRole("menuitem", { name: "Settings" }).click();
        await page
          .getByRole("button", { name: "Channels", exact: true })
          .click();
        await page
          .getByRole("dialog", { name: "Settings", exact: true })
          .getByRole("button", { name: "Connect", exact: true })
          .click();
      } else {
        await sidebar
          .getByRole("button", { name: "Connect", exact: true })
          .click();
      }
      const dialog = page.getByRole("dialog", {
        name: "Connect WeChat",
        exact: true,
      });
      if (flow === "manual token") {
        await dialog.getByRole("tab", { name: "Use token" }).click();
        await dialog.getByLabel("Bot token").fill("manual-demo-token");
        await dialog.getByRole("button", { name: "Save and connect" }).click();
      }
      await expect(
        dialog.getByText("/connect recovery-demo", { exact: true }),
      ).toBeVisible();
      expect(bindingCalls).toBe(1);
      await expect(
        page.locator("[data-sonner-toast]").getByText(/Send \/connect/),
      ).toHaveCount(0);
      const startsBeforeRecovery = qrStarts;
      await dialog
        .getByRole("button", { name: "Scan again", exact: true })
        .click();
      // Saved providers normally default to the token tab; recovery must force QR.
      await expect(
        page.getByRole("dialog").filter({
          has: page.getByRole("img", { name: "WeChat login QR code" }),
        }),
      ).toBeVisible();
      expect(qrStarts).toBe(startsBeforeRecovery + 1);
    });
  }
}
