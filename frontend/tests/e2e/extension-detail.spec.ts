import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("backend-only writing instructions and optional prerequisites are visible", async ({
  page,
  baseURL,
}) => {
  await page
    .context()
    .addCookies([{ name: "locale", value: "zh-CN", url: baseURL! }]);
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/plugins", (route) => route.fulfill({ json: [] }));
  await page.setViewportSize({ width: 1512, height: 1000 });
  await page.goto(
    "/workspace/capabilities?tab=extensions&extension=community.report-sections",
  );
  await expect(page.getByRole("heading", { name: "汇总并下载" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "使用前准备" })).toHaveCount(
    0,
  );
  await expect(page.getByRole("heading", { name: "工作区入口" })).toHaveCount(
    0,
  );
  const directory = process.env.CAPABILITY_SCREENSHOT_DIR;
  if (directory) {
    await mkdir(directory, { recursive: true });
    await page.screenshot({
      path: path.join(directory, "report-sections-desktop.png"),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBe(0);
  if (directory)
    await page.screenshot({
      path: path.join(directory, "report-sections-mobile.png"),
      fullPage: true,
    });
  await page.goto(
    "/workspace/capabilities?tab=extensions&extension=community.jev-context",
  );
  await expect(page.getByRole("heading", { name: "使用前准备" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "达到阈值时自动处理" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 1512, height: 1000 });
  if (directory)
    await page.screenshot({
      path: path.join(directory, "context-pruning-desktop.png"),
      fullPage: true,
    });
});

const modulePath = `/api/plugins/modules/teams.v1/${"a".repeat(64)}.mjs`;
const moduleSource = `export default {
  apiVersion: 1, module: "teams.v1",
  surfaces: [{ id: "teams", slot: "page", title: "Agent teams",
    navigation: {label: "Agent teams", labelZh: "Agent 团队"},
    mount(root) {
      const heading = document.createElement("h2");
      heading.textContent = "Team workspace loaded";
      root.append(heading);
      return {dispose() { heading.remove(); }};
    }
  }]
};`;

for (const locale of ["zh-CN", "en-US"]) {
  test(`extension detail opens its installed page and fits desktop/mobile (${locale})`, async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(120_000);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page
      .context()
      .addCookies([{ name: "locale", value: locale, url: baseURL! }]);
    mockLangGraphAPI(page, { threads: [] });
    await page.route("**/api/plugins", (route) =>
      route.fulfill({
        json: [
          {
            namespace: "community.agent-teams",
            module: "teams.v1",
            entry: modulePath,
            title: "Agent teams",
            description: "Team work",
            settings: { enabled: true },
          },
        ],
      }),
    );
    await page.route(`**${modulePath}`, (route) =>
      route.fulfill({ contentType: "text/javascript", body: moduleSource }),
    );
    await page.setViewportSize({ width: 1512, height: 1050 });
    await page.goto(
      "/workspace/capabilities?tab=extensions&extension=community.agent-teams",
    );
    const zh = locale === "zh-CN";
    const open = page.getByRole("link", {
      name: zh ? "打开 Agent 团队" : "Open Agent teams",
      exact: true,
    });
    await expect(open).toHaveAttribute(
      "href",
      "/workspace/extensions/community.agent-teams/teams",
    );
    await expect(
      page.getByRole("heading", {
        name: zh ? "组建你的团队" : "Build your team",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByText("deerflow-extension-agent-teams", { exact: true }),
    ).not.toBeVisible();
    const directory = process.env.CAPABILITY_SCREENSHOT_DIR;
    if (directory) {
      await mkdir(directory, { recursive: true });
      await page.screenshot({
        path: path.join(directory, `extension-detail-${locale}-desktop.png`),
        fullPage: true,
      });
    }
    await open.click();
    await expect(page).toHaveURL(
      /\/workspace\/extensions\/community.agent-teams\/teams$/,
      { timeout: 30_000 },
    );
    await expect(
      page.getByRole("heading", { name: "Team workspace loaded" }),
    ).toBeVisible();
    await page.goto(
      "/workspace/capabilities?tab=extensions&extension=community.agent-teams",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(open).toBeInViewport({ ratio: 1 });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        ),
      )
      .toBe(0);
    const article = page.getByRole("article");
    expect(
      await article.evaluate((node) => node.scrollWidth - node.clientWidth),
    ).toBe(0);
    if (directory)
      await page.screenshot({
        path: path.join(directory, `extension-detail-${locale}-mobile.png`),
        fullPage: true,
      });
    await page
      .getByText(zh ? "技术信息" : "Technical details", { exact: true })
      .click();
    await expect(
      page.getByText("deerflow-extension-agent-teams", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: zh ? "刷新扩展" : "Refresh extensions",
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", {
        name: zh ? "全部扩展" : "All extensions",
        exact: true,
      })
      .click();
    await expect(
      page.getByPlaceholder(
        zh ? "按名称或用途搜索扩展" : "Search extensions by name or purpose",
      ),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
}
