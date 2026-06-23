import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const channelProviders = [
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
  onFeishuConnect?: () => void,
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

  void page.route("**/api/channels/feishu/connect", (route) => {
    onFeishuConnect?.();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provider: "feishu",
        mode: "binding_code",
        url: null,
        code: "abc123",
        instruction: "Send /connect abc123 to the DeerFlow Feishu bot.",
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
    await expect(sidebar.getByText("Feishu")).toBeVisible();
    await expect(sidebar.getByText("DingTalk")).toBeVisible();
    await expect(sidebar.getByText("WeChat")).toBeVisible();
    await expect(sidebar.getByText("WeCom")).toBeVisible();
    await expect(
      sidebar.getByRole("button", { name: "Connected" }),
    ).toHaveCount(4);

    await sidebar.getByRole("button", { name: /Settings and more/ }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Channels" }).click();

    await expect(page.getByText("Feishu and Lark messages")).toBeVisible();
    await expect(page.getByText("DingTalk Stream Push messages")).toBeVisible();
    await expect(page.getByText("WeChat iLink messages")).toBeVisible();
    await expect(page.getByText("WeCom messages")).toBeVisible();

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog.getByRole("button", { name: "Modify" })).toHaveCount(4);
  });

  test("only enabled providers are shown and runtime setup stays editable", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let feishuConfigured = false;
    let submittedValues: Record<string, string> | undefined;

    void page.route("**/api/channels/providers", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          providers: [
            {
              provider: "feishu",
              display_name: "Feishu",
              enabled: true,
              configured: feishuConfigured,
              connectable: feishuConfigured,
              auth_mode: "binding_code",
              connection_status: feishuConfigured
                ? "connected"
                : "not_connected",
              credential_fields: [
                {
                  name: "app_id",
                  label: "App ID",
                  type: "password",
                  required: true,
                },
                {
                  name: "app_secret",
                  label: "App secret",
                  type: "password",
                  required: true,
                },
              ],
              credential_values: feishuConfigured
                ? {
                    app_id: "********",
                    app_secret: "********",
                  }
                : {},
            },
            {
              provider: "dingtalk",
              display_name: "DingTalk",
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

    void page.route("**/api/channels/feishu/runtime-config", async (route) => {
      const body = route.request().postDataJSON() as {
        values: Record<string, string>;
      };
      submittedValues = body.values;
      feishuConfigured = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider: "feishu",
          display_name: "Feishu",
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

    void page.route("**/api/channels/feishu/connect", (route) =>
      route.abort(),
    );

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Feishu")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.getByText("DingTalk")).toBeHidden();
    const connectButton = sidebar.getByRole("button", { name: "Connect" });
    await expect(connectButton).toBeEnabled();

    await connectButton.click();

    const setupDialog = page.getByRole("dialog", { name: "Connect Feishu" });
    await expect(setupDialog).toBeVisible();
    const appIdInput = setupDialog.getByLabel("App ID");
    await expect(appIdInput).toHaveAttribute("type", "text");
    await expect(appIdInput).toHaveAttribute("autocomplete", "off");
    await expect(appIdInput).toHaveAttribute("data-lpignore", "true");
    await expect(appIdInput).toHaveAttribute("data-1p-ignore", "true");
    await expect(appIdInput).toHaveCSS("-webkit-text-security", "disc");
    await setupDialog.getByLabel("App ID").fill("feishu-app-id");
    await setupDialog.getByLabel("App secret").fill("secret-value");
    await setupDialog
      .getByRole("button", { name: "Save and connect" })
      .click();

    await expect(setupDialog).toBeHidden();
    await expect(
      sidebar.getByRole("button", { name: "Connected" }),
    ).toBeVisible();
    await sidebar.getByRole("button", { name: "Connected" }).click();
    await expect(
      page.getByRole("dialog", { name: "Modify Feishu" }),
    ).toBeVisible();
    await expect(page.getByLabel("App ID")).toHaveValue("********");
    await expect(page.getByLabel("App secret")).toHaveValue("********");
    expect(submittedValues).toEqual({
      app_id: "feishu-app-id",
      app_secret: "secret-value",
    });
  });

  test("configured provider connects directly with a binding-code instruction", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let feishuConnectCalls = 0;
    mockChannelsAPI(
      page,
      [
        {
          provider: "feishu",
          display_name: "Feishu",
          enabled: true,
          configured: true,
          connectable: true,
          auth_mode: "binding_code",
          connection_status: "not_connected",
          credential_fields: [
            {
              name: "app_id",
              label: "App ID",
              type: "password",
              required: true,
            },
          ],
          credential_values: { app_id: "********" },
        },
      ],
      () => {
        feishuConnectCalls += 1;
      },
    );

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Feishu")).toBeVisible({
      timeout: 15_000,
    });
    await sidebar.getByRole("button", { name: "Connect" }).click();

    await expect(
      page.getByText("Send /connect abc123 to the DeerFlow Feishu bot."),
    ).toBeVisible();
    expect(feishuConnectCalls).toBe(1);
  });

  test("runtime setup continues into the connect flow when a binding is still required", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let feishuConfigured = false;
    let feishuConnectCalls = 0;

    void page.route("**/api/channels/providers", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          providers: [
            {
              provider: "feishu",
              display_name: "Feishu",
              enabled: true,
              configured: feishuConfigured,
              connectable: feishuConfigured,
              auth_mode: "binding_code",
              connection_status: "not_connected",
              credential_fields: [
                {
                  name: "app_id",
                  label: "App ID",
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

    void page.route(
      "**/api/channels/feishu/runtime-config",
      (route) => {
        feishuConfigured = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            provider: "feishu",
            display_name: "Feishu",
            enabled: true,
            configured: true,
            connectable: true,
            auth_mode: "binding_code",
            connection_status: "not_connected",
            credential_fields: [],
            credential_values: {},
          }),
        });
      },
    );

    void page.route("**/api/channels/feishu/connect", (route) => {
      feishuConnectCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider: "feishu",
          mode: "binding_code",
          url: null,
          code: "abc123",
          instruction:
            "Send /connect abc123 to the DeerFlow Feishu bot.",
          expires_in: 600,
        }),
      });
    });

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.getByText("Feishu")).toBeVisible({
      timeout: 15_000,
    });
    await sidebar.getByRole("button", { name: "Connect" }).click();

    const setupDialog = page.getByRole("dialog", {
      name: "Connect Feishu",
    });
    await expect(setupDialog).toBeVisible();
    await setupDialog.getByLabel("App ID").fill("feishu-app-id");
    await setupDialog
      .getByRole("button", { name: "Save and connect" })
      .click();

    await expect(setupDialog).toBeHidden();
    await expect(
      page.getByText(
        "Send /connect abc123 to the DeerFlow Feishu bot.",
      ),
    ).toBeVisible();
    expect(feishuConnectCalls).toBe(1);
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
    await expect(sidebar.getByText("Feishu")).toBeVisible({
      timeout: 15_000,
    });
    await sidebar.getByRole("button", { name: "Connected" }).click();

    const setupDialog = page.getByRole("dialog", {
      name: "Modify Feishu",
    });
    await expect(setupDialog).toBeVisible();
    await expect(setupDialog.getByLabel("App ID")).toHaveValue(
      "cli_feishu_app",
    );
    await expect(setupDialog.getByLabel("App secret")).toHaveValue("********");
  });
});