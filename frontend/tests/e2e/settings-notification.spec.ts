import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

declare global {
  interface Window {
    __deerflowNotifications?: Array<{ title: string; body?: string }>;
  }
}

async function installNotificationMock(
  page: Page,
  initialPermission: NotificationPermission = "default",
) {
  await page.addInitScript((permission) => {
    window.__deerflowNotifications = [];

    class MockNotification {
      static permission: NotificationPermission = permission;

      static async requestPermission(): Promise<NotificationPermission> {
        MockNotification.permission = "granted";
        return "granted";
      }

      onclick: (() => void) | null = null;
      onerror: ((error: Event) => void) | null = null;
      closed = false;

      constructor(title: string, options?: NotificationOptions) {
        window.__deerflowNotifications?.push({
          title,
          body: options?.body,
        });
      }

      close() {
        this.closed = true;
      }
    }

    Object.defineProperty(window, "Notification", {
      configurable: true,
      value: MockNotification,
    });
  }, initialPermission);
}

async function openNotificationSettings(page: Page) {
  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Notification" }).click();
  return dialog;
}

test.describe("Notification settings", () => {
  test("can request permission and send the first test notification immediately", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await installNotificationMock(page);

    const dialog = await openNotificationSettings(page);
    await dialog
      .getByRole("button", { name: "Request notification permission" })
      .click();

    await expect(
      dialog.getByRole("switch", { name: "Notification" }),
    ).toBeChecked();

    await dialog
      .getByRole("button", { name: "Send test notification" })
      .click();

    await expect
      .poll(() => page.evaluate(() => window.__deerflowNotifications ?? []))
      .toEqual([
        {
          title: "DeerFlow",
          body: "This is a test notification.",
        },
      ]);
  });

  test("sends a completion notification when chat finishes while the page is unfocused", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await installNotificationMock(page, "granted");
    await page.addInitScript(() => {
      Document.prototype.hasFocus = () => false;
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Run a one minute task");
    await textarea.press("Enter");

    await expect
      .poll(() => page.evaluate(() => window.__deerflowNotifications ?? []))
      .toEqual([
        {
          title: "New Chat",
          body: "Hello from DeerFlow!",
        },
      ]);
  });
});
