import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

function configuredLarkStatus() {
  return {
    installed: true,
    version: "v1.0.65",
    manifest_version: "v1.0.65",
    latest_available_version: "v1.0.65",
    runtime_version_mismatch: false,
    app_configured: true,
    app_id: "cli_existing_mock",
    app_brand: "feishu",
    skills_expected: 27,
    skills_installed: 4,
    installed_skills: ["lark-doc", "lark-im", "lark-shared", "lark-sheets"],
    enabled_skills: ["lark-doc", "lark-im", "lark-shared", "lark-sheets"],
    install_path: "/mock/integrations/skills/lark-cli",
    cli: {
      available: true,
      path: "/usr/bin/lark-cli",
      version: "lark-cli version v1.0.65",
      error: null,
    },
    auth: {
      status: "authenticated",
      message: "Lark authorization is live-verified.",
      user: "existing-user",
      verified: true,
    },
    sandbox_runtime_mode: "none",
    sandbox_runtime_ready: false,
    sandbox_runtime_detail: null,
  };
}

test.describe("Integrations settings", () => {
  test("opens integrations settings from a query-string deep link", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new?settings=integrations");

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Lark / Feishu CLI")).toBeVisible();
  });

  test("keeps a single settings dialog across deep link and nav menu openings", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    // Deep link opens the shared dialog on Integrations.
    await page.goto("/workspace/chats/new?settings=integrations");
    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Lark / Feishu CLI")).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(1);

    // Close the modal before using the sidebar. While the modal is open, the
    // background is intentionally inert and Playwright should not be able to
    // click sidebar controls there.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(0);

    // Opening again from the nav menu must still use the same shared host, not
    // mount a second SettingsDialog instance.
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await sidebar.getByRole("button", { name: /Settings and more/ }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();

    // Exactly one Settings dialog is mounted/visible at any time.
    await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(1);
  });

  test("can install the Lark integration skill pack from settings", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let authStartRequest: unknown;
    const authCompleteRequests: unknown[] = [];
    let authCompleteCount = 0;
    await page.route(
      "**/api/integrations/lark/auth/complete",
      async (route) => {
        authCompleteRequests.push(route.request().postDataJSON());
        authCompleteCount += 1;
        if (authCompleteCount > 1) {
          await route.fulfill({
            status: 504,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Authorization still pending." }),
          });
          return;
        }
        await route.fallback();
      },
    );
    await page.route("**/api/integrations/lark/config/start", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          verification_url: "about:blank",
          device_code: "mock-config-device-code",
          generation: "config-generation",
          expires_in: 600,
          interval: 5,
          user_code: "config",
          brand: "feishu",
        }),
      });
    });
    await page.route("**/api/integrations/lark/auth/start", async (route) => {
      authStartRequest = route.request().postDataJSON();
      const request = authStartRequest as { generation?: string };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          verification_url: "https://open.feishu.cn/auth/mock-device",
          device_code: "mock-device-code",
          generation: request.generation ?? "auth-generation",
          expires_in: 600,
          user_code: null,
          hint: null,
        }),
      });
    });

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    await sidebar.getByRole("button", { name: /Settings and more/ }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Integrations" }).click();

    await expect(dialog.getByText("Lark / Feishu CLI")).toBeVisible();
    await expect(
      dialog.getByText("Install the official skill pack first"),
    ).toBeVisible();

    await dialog.getByRole("button", { name: "Install" }).click();
    await expect(
      page.getByText("Installed 3 Lark/Feishu skills."),
    ).toBeVisible();

    // Sandbox-runtime readiness row surfaces once the init-container runtime is
    // reported ready, so a green UI can't hide a chat-time command-not-found.
    await expect(dialog.getByText("Sandbox runtime")).toBeVisible();
    await expect(
      dialog.getByText("Provisioned by init container"),
    ).toBeVisible();

    await dialog.getByRole("button", { name: "Calendar" }).click();
    await dialog
      .getByLabel("Exact OAuth scope")
      .fill("calendar:calendar.event:read");
    await dialog.getByRole("button", { name: "Connect Lark" }).click();
    await expect(dialog.getByText("about:blank")).toBeVisible();
    await expect(dialog.getByText(/app configuration/i)).toHaveCount(0);

    await dialog
      .getByRole("button", {
        name: "I completed browser confirmation, continue",
      })
      .click();
    await expect
      .poll(() => authStartRequest)
      .toMatchObject({
        recommend: false,
        domains: ["calendar"],
        scope: "calendar:calendar.event:read",
        generation: "config-generation",
      });

    await expect
      .poll(() => authCompleteRequests)
      .toContainEqual({
        device_code: "mock-device-code",
        generation: "config-generation",
        wait_timeout_seconds: 8,
      });
    await expect(
      dialog.getByText("Lark authorization is live-verified"),
    ).toBeVisible();
    await expect(
      page.getByText("Authorization page opened. Waiting for completion..."),
    ).toHaveCount(0);

    await dialog.getByRole("button", { name: "Calendar" }).click();
    await dialog.getByLabel("Exact OAuth scope").fill("");
    await dialog.getByRole("button", { name: "Reconnect Lark" }).click();
    await expect(
      dialog.getByText("https://open.feishu.cn/auth/mock-device"),
    ).toBeVisible();
  });

  test("can switch the Lark app by entering new credentials", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    // A configured + CLI-available account is the precondition for surfacing
    // the "Change Lark app" control.
    const configuredStatus = configuredLarkStatus();
    await page.route("**/api/integrations/lark/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(configuredStatus),
      });
    });

    let credentialsRequest: unknown;
    let releaseCredentials!: () => void;
    const credentialsGate = new Promise<void>((resolve) => {
      releaseCredentials = resolve;
    });
    await page.route(
      "**/api/integrations/lark/config/credentials",
      async (route) => {
        credentialsRequest = route.request().postDataJSON();
        await credentialsGate;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            message:
              "Lark/Feishu app switched. Reconnect to authorize the new app.",
            generation: "switch-generation",
            status: {
              ...configuredStatus,
              app_id: "cli_new_mock",
              auth: {
                status: "not_authorized",
                message: "not authorized",
                user: null,
                verified: false,
              },
            },
          }),
        });
      },
    );
    let authStartRequest: unknown;
    await page.route("**/api/integrations/lark/auth/start", async (route) => {
      authStartRequest = route.request().postDataJSON();
      const request = authStartRequest as { generation?: string };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          verification_url: "https://open.feishu.cn/auth/switched-app",
          device_code: "switched-device-code",
          generation: request.generation ?? "auth-generation",
          expires_in: 600,
          user_code: null,
          hint: null,
        }),
      });
    });

    await page.goto("/workspace/chats/new?settings=integrations");

    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Lark / Feishu CLI")).toBeVisible();

    // Reveal the switch form and submit new app credentials.
    await dialog.getByRole("button", { name: "Change Lark app" }).click();
    await expect(
      dialog.getByText("Switch to a different Lark app"),
    ).toBeVisible();
    await dialog.getByLabel("App ID").fill("cli_new_mock");
    await dialog.getByLabel("App Secret").fill("super-secret");
    const popupPromise = page.waitForEvent("popup");
    await dialog.getByRole("button", { name: "Switch app" }).click();
    const popup = await popupPromise;
    await expect(
      dialog.getByRole("button", { name: "Opening connection link..." }),
    ).toBeDisabled();
    await expect(
      dialog.getByRole("button", { name: "Re-register in browser" }),
    ).toBeDisabled();
    releaseCredentials();

    await expect
      .poll(() => credentialsRequest)
      .toMatchObject({
        app_id: "cli_new_mock",
        app_secret: "super-secret",
        brand: "feishu",
      });

    // Switching a bot immediately drives the new app's browser authorization.
    await expect
      .poll(() => authStartRequest)
      .toEqual({
        recommend: false,
        domains: [],
        scope: null,
        generation: "switch-generation",
      });
    await expect
      .poll(() => popup.url())
      .toBe("https://open.feishu.cn/auth/switched-app");
    await popup.close();
  });

  test("keeps selected permissions when re-registering the Lark app", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    const configuredStatus = configuredLarkStatus();
    await page.route("**/api/integrations/lark/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(configuredStatus),
      });
    });
    let authStartRequest: unknown;
    await page.route("**/api/integrations/lark/auth/start", async (route) => {
      authStartRequest = route.request().postDataJSON();
      await route.fallback();
    });

    await page.goto("/workspace/chats/new?settings=integrations");
    const dialog = page.getByRole("dialog", { name: "Settings" });
    await dialog.getByRole("button", { name: "Calendar" }).click();
    await dialog
      .getByLabel("Exact OAuth scope")
      .fill("calendar:calendar.event:read");
    await dialog.getByRole("button", { name: "Change Lark app" }).click();
    const popupPromise = page.waitForEvent("popup");
    await dialog
      .getByRole("button", { name: "Re-register in browser" })
      .click();
    const popup = await popupPromise;
    await dialog
      .getByRole("button", {
        name: "I completed browser confirmation, continue",
      })
      .click();

    await expect
      .poll(() => authStartRequest)
      .toEqual({
        recommend: false,
        domains: ["calendar"],
        scope: "calendar:calendar.event:read",
        generation: "config-generation",
      });
    await popup.close();
  });
});
