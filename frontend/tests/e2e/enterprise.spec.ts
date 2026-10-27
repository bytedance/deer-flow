import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("enterprise page keeps WeCom and Alibaba mail connections", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  let connected = false;
  await page.route("**/api/enterprise{,/**}", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/mail")) {
      await route.fulfill({ json: { accounts: [] } });
    } else if (path.endsWith("/targets") && request.method() === "POST") {
      expect(request.postDataJSON()).toEqual({
        name: "Operations",
        webhook:
          "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic",
        provider: "wecom_webhook",
      });
      connected = true;
      await route.fulfill({
        json: {
          id: "group1",
          name: "Operations",
          provider: "wecom_webhook",
          enabled: true,
        },
      });
    } else {
      await route.fulfill({
        json: {
          targets: connected
            ? [
                {
                  id: "group1",
                  name: "Operations",
                  provider: "wecom_webhook",
                  enabled: true,
                },
              ]
            : [],
          deliveries: [],
          scheduler_enabled: true,
        },
      });
    }
  });
  await page.goto("/workspace/enterprise");
  await expect(
    page.getByRole("heading", { name: "Enterprise connections", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Alibaba enterprise mail" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Bind group", exact: true }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Operations");
  await page
    .getByLabel("Group robot webhook URL", { exact: true })
    .fill("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic");
  await page.getByRole("button", { name: "Save connection" }).click();
  await expect(page.getByLabel("Group robot webhook URL")).toHaveCount(0);
  await expect(page.getByText("Operations", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2 })).toHaveText([
    "WeCom groups",
    /^Alibaba enterprise mail/,
  ]);
  await page.screenshot({
    path: test.info().outputPath("enterprise-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
