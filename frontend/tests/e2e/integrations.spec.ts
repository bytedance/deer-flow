import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

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
    await page.route(
      "**/api/integrations/lark/auth/complete",
      async (route) => {
        authCompleteRequests.push(route.request().postDataJSON());
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
          expires_in: 600,
          interval: 5,
          user_code: "config",
          brand: "feishu",
        }),
      });
    });
    await page.route("**/api/integrations/lark/auth/start", async (route) => {
      authStartRequest = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          verification_url: "https://open.feishu.cn/auth/mock-device",
          device_code: "mock-device-code",
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
      });

    await expect
      .poll(() => authCompleteRequests)
      .toContainEqual({
        device_code: "mock-device-code",
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
});
