import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const skills = [
  {
    name: "deep-research",
    description:
      "Search, cross-check sources, and write a detailed research report.",
  },
  {
    name: "data-analysis",
    description: "Analyze structured data and create charts.",
  },
  {
    name: "academic-paper-review",
    description:
      "Review research papers, methods, contributions, and limitations.",
  },
  {
    name: "ppt-generation",
    description: "Create presentations from ideas and reference materials.",
  },
  {
    name: "frontend-design",
    description: "Build polished frontend interfaces.",
  },
  {
    name: "image-generation",
    description: "Generate images from a written description.",
  },
  {
    name: "podcast-generation",
    description: "Create podcast scripts and audio.",
  },
  {
    name: "skill-creator",
    description: "Create reusable skills for new tasks.",
  },
  {
    name: "skill-reviewer",
    description: "Review skill quality and report potential issues.",
  },
].map((skill) => ({
  ...skill,
  category: "public",
  enabled: true,
  license: "MIT",
}));

async function mockCatalog(page: Page) {
  mockLangGraphAPI(page, { skills, threads: [] });
  await page.route("**/api/mcp/config", (route) =>
    route.fulfill({
      json: {
        mcp_servers: {
          GitHub: {
            description:
              "搜索代码与仓库，查看 Issue 和 Pull Request，协助推进开发工作。",
            enabled: true,
            type: "http",
            url: "https://example.test/github",
          },
          Notion: {
            description: "搜索工作空间里的笔记和文档，整理资料，创建新的页面。",
            enabled: true,
            type: "http",
            url: "https://example.test/notion",
          },
          "Brave Search": {
            description: "搜索互联网上的信息，为研究、写作和决策补充最新资料。",
            enabled: true,
            command: "example-search",
          },
          Filesystem: {
            description: "访问已授权的文件夹，读取文件内容并整理本地工作资料。",
            enabled: true,
            command: "example-files",
          },
          PostgreSQL: {
            description: "查询数据库中的业务数据，探索表结构，辅助数据分析。",
            enabled: false,
            command: "example-database",
          },
        },
      },
    }),
  );
}

async function screenshot(page: Page, name: string) {
  const directory = process.env.CAPABILITY_SCREENSHOT_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, name), fullPage: true });
}

test("catalog navigation, search, details, and migrated settings", async ({
  page,
  baseURL,
}) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1512, height: 1060 });
  await page
    .context()
    .addCookies([{ name: "locale", value: "zh-CN", url: baseURL! }]);
  await mockCatalog(page);
  await page.goto("/workspace/capabilities");
  await expect(
    page.getByRole("heading", { name: "能力中心", exact: true }),
  ).toBeVisible();
  await expect(page.locator("article")).toHaveCount(6);
  await expect(page.locator("a[href='/workspace/capabilities']")).toBeVisible();
  await screenshot(page, "capability-center-plugins.png");

  await page
    .getByRole("textbox", { name: "搜索插件名称或用途" })
    .fill("Notion");
  await expect(page.locator("article")).toHaveCount(1);
  await page.getByRole("button", { name: "编辑 Notion", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "MCP 服务器 JSON 定义" }),
  ).toHaveValue(/example.test\/notion/);
  await page.keyboard.press("Escape");
  await page.getByRole("tab", { name: "技能", exact: true }).click();
  await expect(page.locator("article")).toHaveCount(9);
  await expect(
    page.getByRole("button", { name: "查看详情 深度研究", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 1512, height: 1270 });
  await screenshot(page, "capability-center-skills.png");
  await page
    .getByRole("button", { name: "查看详情 深度研究", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").getByText(skills[0]!.description),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("tab", { name: "社区", exact: true }).click();
  await expect(page.getByText("从社区带来新的技能")).toBeVisible();

  await page.goto("/workspace/capabilities?settings=appearance");
  const settings = page.getByRole("dialog", { name: "设置", exact: true });
  await expect(settings).toBeVisible();
  for (const name of ["工具", "集成", "技能"]) {
    await expect(
      settings.getByRole("button", { name, exact: true }),
    ).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});

test("the skills catalog fits a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockCatalog(page);
  await page.goto("/workspace/capabilities?tab=skills");
  await expect(page).toHaveURL(/workspace\/capabilities\?tab=skills/);
  await expect(page.locator("article")).toHaveCount(9);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Toggle Sidebar", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "Capability Center" }),
  ).toBeVisible();
});

test("MCP access errors preserve the independently available Lark integration", async ({
  page,
}) => {
  await mockCatalog(page);
  await page.route("**/api/mcp/config", (route) =>
    route.fulfill({ status: 403, json: { detail: "Admin only" } }),
  );
  await page.goto("/workspace/capabilities");
  await expect(
    page.getByRole("alert").filter({ hasText: "Admin privileges" }),
  ).toBeVisible();
  await expect(
    page.locator("article").filter({ hasText: "Lark / Feishu" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add MCP plugin" }),
  ).toHaveCount(0);
});

test("Community search gives feedback and clearing it restores import guidance", async ({
  page,
}) => {
  await mockCatalog(page);
  await page.goto("/workspace/capabilities?tab=skills");
  await expect(page.locator("article")).toHaveCount(9);
  const search = page.getByRole("textbox", {
    name: "Search skills by name or purpose",
  });
  await search.fill("nonexistent-query");
  await expect(
    page.getByText("No matches found", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Community", exact: true }).click();
  await expect(search).toHaveValue("nonexistent-query");
  await expect(
    page.getByText("No matches found", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Bring a skill from the community", { exact: true }),
  ).toHaveCount(0);
  await search.fill("   ");
  await expect(
    page.getByText("Bring a skill from the community", { exact: true }),
  ).toBeVisible();
  await search.fill("");
  await page.getByRole("tab", { name: "Built-in", exact: true }).click();
  await expect(page.locator("article")).toHaveCount(9);
});

test("plugin filters remain usable after an MCP refetch fails", async ({
  page,
}) => {
  await mockCatalog(page);
  let failRead = false;
  await page.route("**/api/mcp/config", async (route) => {
    if (route.request().method() === "PATCH") {
      failRead = true;
      return route.fulfill({ json: { mcp_servers: {} } });
    }
    if (failRead)
      return route.fulfill({ status: 403, json: { detail: "Admin only" } });
    return route.fallback();
  });
  await page.goto("/workspace/capabilities");
  await expect(page.locator("article")).toHaveCount(6);
  const installed = page.getByRole("tab", { name: "Installed", exact: true });
  await installed.click();
  await expect(page.locator("article")).toHaveCount(5);
  await page
    .getByRole("switch", { name: "Enabled GitHub", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(installed).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByRole("button", { name: "Add MCP plugin" }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "All plugins", exact: true }).click();
  await expect(
    page.locator("article").filter({ hasText: "Lark / Feishu" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Configure Lark / Feishu", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
});
