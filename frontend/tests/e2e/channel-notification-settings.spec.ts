import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";
import { setLocaleCookie } from "./utils/scheduled-fixtures";

const defaults = { feishu: true, wecom: true, wechat: true, qq: true };
const channelProviders = ["feishu", "wecom", "wechat", "qq"].map(
  (provider) => ({
    provider,
    display_name: provider,
    auth_mode: "connect_code",
    connection_status: "connected",
    proactive_notifications: true,
  }),
);

async function openSettings(page: Page, chinese = false) {
  await page.goto("/workspace/chats/new");
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: chinese ? /设置和更多/ : /Settings and more/ })
    .click();
  await page
    .getByRole("menuitem", { name: chinese ? "设置" : "Settings", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: chinese ? "设置" : "Settings",
    exact: true,
  });
  await dialog
    .getByRole("button", {
      name: chinese ? "通知" : "Notification",
      exact: true,
    })
    .click();
  return dialog;
}

test("one shared panel saves channel preferences independently of browser notifications", async ({
  page,
}) => {
  mockLangGraphAPI(page, { channelProviders });
  let preferences = { ...defaults };
  const patches: unknown[] = [];
  await page.route(
    "**/api/channels/notification-preferences",
    async (route) => {
      if (route.request().method() === "PATCH") {
        const patch = route.request().postDataJSON() as Partial<
          typeof defaults
        >;
        patches.push(patch);
        expect(route.request().headers()["x-expected-user-id"]).toBeTruthy();
        preferences = { ...preferences, ...patch };
      }
      await route.fulfill({ json: preferences });
    },
  );
  const dialog = await openSettings(page);
  const feishu = dialog.getByRole("switch", {
    name: "Feishu / Lark scheduled task notifications",
  });
  await expect(feishu).toBeChecked();
  await expect(
    dialog.getByRole("switch", { name: "QQ scheduled task notifications" }),
  ).toBeChecked();
  await feishu.click();
  await expect(feishu).not.toBeChecked();
  expect(patches).toEqual([{ feishu: false }]);
  await expect(
    dialog.getByRole("switch", { name: "WeCom scheduled task notifications" }),
  ).toBeChecked();
  await expect(dialog.getByText(/does not affect chatting/)).toBeVisible();
  await page.reload();
  // Reload reads the stored server preference, with no extra write.
  const reopened = await openSettings(page);
  await expect(
    reopened.getByRole("switch", {
      name: "Feishu / Lark scheduled task notifications",
    }),
  ).not.toBeChecked();
  expect(patches).toHaveLength(1);
});

test("failed saves keep the confirmed value and offer a retry through the switch", async ({
  page,
}) => {
  mockLangGraphAPI(page, { channelProviders });
  await page.route("**/api/channels/notification-preferences", (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({ status: 503, json: { detail: "unavailable" } })
      : route.fulfill({ json: defaults }),
  );
  const dialog = await openSettings(page);
  const toggle = dialog.getByRole("switch", {
    name: "WeChat scheduled task notifications",
  });
  await expect(toggle).toBeChecked();
  await toggle.click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Could not save this change",
  );
  await expect(toggle).toBeChecked();
  await expect(toggle).toBeEnabled();
});

test("Chinese settings show all four supported channels and no unavailable event types", async ({
  page,
}) => {
  await setLocaleCookie(page, "zh");
  mockLangGraphAPI(page, { channelProviders });
  await page.route("**/api/channels/notification-preferences", (route) =>
    route.fulfill({ json: defaults }),
  );
  const dialog = await openSettings(page, true);
  for (const provider of ["飞书 / Lark", "企业微信", "微信", "QQ"]) {
    await expect(
      dialog.getByRole("switch", {
        name: `${provider}定时任务通知`,
        exact: true,
      }),
    ).toBeChecked();
  }
  await expect(dialog.getByText(/关闭通知不影响聊天/)).toBeVisible();
});

test("an older Gateway exposes no pretend channel switches", async ({
  page,
}) => {
  mockLangGraphAPI(page, { channelProviders });
  await page.route("**/api/channels/notification-preferences", (route) =>
    route.fulfill({ status: 404, json: { detail: "Not found" } }),
  );
  const dialog = await openSettings(page);
  await expect(
    dialog.getByText(
      "This service does not support notification preferences yet.",
    ),
  ).toBeVisible();
  await expect(
    dialog.getByRole("switch", { name: /scheduled task notifications/ }),
  ).toHaveCount(0);
});
