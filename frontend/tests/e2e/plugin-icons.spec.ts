import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { type MCPServerConfig } from "../../src/core/mcp/types";

import { mockLangGraphAPI } from "./utils/mock-api";

async function screenshot(page: Page, name: string) {
  const directory = process.env.CAPABILITY_SCREENSHOT_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.screenshot({
    path: path.join(directory, name),
    fullPage: true,
    animations: "disabled",
  });
}

async function sampleImage(page: Page, mimeType = "image/png") {
  const data = await page.evaluate((mimeType) => {
    const canvas = document.createElement("canvas");
    canvas.width = 300;
    canvas.height = 180;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#3159d8";
    ctx.fillRect(0, 0, 300, 180);
    ctx.fillStyle = "white";
    ctx.font = "bold 78px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("AC", 150, 118);
    return canvas.toDataURL(mimeType).split(",")[1]!;
  }, mimeType);
  return {
    name: "acme.png",
    mimeType,
    buffer: Buffer.from(data, "base64"),
  };
}

test("brand icons load locally for both recommendations and configured MCP servers", async ({
  page,
  baseURL,
}) => {
  await page.setViewportSize({ width: 1512, height: 1700 });
  await page
    .context()
    .addCookies([{ name: "locale", value: "zh-CN", url: baseURL! }]);
  mockLangGraphAPI(page);
  await page.route("**/api/mcp/config", (route) =>
    route.fulfill({
      json: {
        mcp_servers: {
          github: {
            capability: {
              id: "fixture-github",
              plugin_id: "github",
              version: "1",
            },
            enabled: false,
            description: "检索代码与仓库，跟进 Issue 与 Pull Request。",
            type: "http",
            url: "https://example.test/github",
          },
          postgres: {
            capability: {
              id: "fixture-postgres",
              plugin_id: "database",
              version: "1",
            },
            enabled: false,
            description: "查询数据库中的业务数据，辅助分析与决策。",
            command: "npx",
          },
        },
      },
    }),
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/workspace/capabilities");
  for (const name of [
    "lark",
    "dingtalk",
    "wecom",
    "tencent-docs",
    "notion",
    "openviking",
    "exa",
    "firecrawl",
    "hubspot",
    "atlassian",
    "github",
  ]) {
    const icon = page.locator(`img[data-plugin-icon="${name}"]`);
    await expect(icon).toHaveCount(1);
    await expect(icon).toHaveAttribute("src", /^\/images\/plugins\//);
    await expect
      .poll(() =>
        icon.evaluate(
          (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
        ),
      )
      .toBe(true);
  }
  // A generic database capability does not assert a specific vendor brand.
  await expect(page.locator('img[data-plugin-icon="postgres"]')).toHaveCount(0);
  await screenshot(page, "plugin-brand-icons-zh.png");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("upload previews, cancellation, save, reload, restore default, and create are functional", async ({
  page,
  baseURL,
}) => {
  await page
    .context()
    .addCookies([{ name: "locale", value: "zh-CN", url: baseURL! }]);
  await page.setViewportSize({ width: 1440, height: 1100 });
  mockLangGraphAPI(page);
  const servers: Record<string, MCPServerConfig> = {
    github: {
      capability: { id: "fixture-github", plugin_id: "github", version: "1" },
      enabled: false,
      description: "GitHub repositories",
      type: "http",
      url: "https://example.test/github",
      headers: { Authorization: "***" },
      presentation: { display_name: "Engineering" },
    },
  };
  let writes = 0;
  await page.route("**/api/mcp/config", (route) =>
    route.fulfill({ json: { mcp_servers: servers } }),
  );
  await page.route("**/api/mcp/config/server", async (route) => {
    writes++;
    const body = route.request().postDataJSON() as {
      server_name: string;
      server: MCPServerConfig;
    };
    servers[body.server_name] = body.server;
    await route.fulfill({ json: { mcp_servers: servers } });
  });
  await page.route("**/api/mcp/config/servers", async (route) => {
    writes++;
    const body = route.request().postDataJSON() as {
      mcp_servers: Record<string, MCPServerConfig>;
    };
    Object.assign(servers, body.mcp_servers);
    await route.fulfill({ json: { mcp_servers: servers } });
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/workspace/capabilities");
  await page.getByRole("button", { name: "编辑 github", exact: true }).click();
  const file = await sampleImage(page);
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles(file);
  await expect(dialog.locator("img")).toHaveAttribute(
    "src",
    /^data:image\/png;base64,/,
  );
  expect(writes).toBe(0);
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page.locator('article img[data-plugin-icon="github"]'),
  ).toHaveAttribute("src", "/images/plugins/github.svg");
  await page.getByRole("button", { name: "编辑 github", exact: true }).click();
  await expect(dialog.locator("img")).toHaveAttribute(
    "src",
    "/images/plugins/github.svg",
  );
  await dialog.locator('input[type="file"]').setInputFiles(file);
  await expect(dialog.locator("img")).toHaveAttribute(
    "src",
    /^data:image\/png;base64,/,
  );
  await screenshot(page, "plugin-icon-editor-zh.png");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes).toBe(1);
  expect(servers.github?.headers).toEqual({ Authorization: "***" });
  expect(servers.github?.presentation?.display_name).toBe("Engineering");
  expect(servers.github?.enabled).toBe(false);
  await page.reload();
  await expect(
    page.locator('article img[data-plugin-icon="github"]'),
  ).toHaveAttribute("src", /^data:image\/png;base64,/);
  // Normalized output is square; the original aspect ratio is preserved with padding.
  await expect
    .poll(() =>
      page
        .locator('article img[data-plugin-icon="github"]')
        .evaluate((img: HTMLImageElement) => [
          img.naturalWidth,
          img.naturalHeight,
        ]),
    )
    .toEqual([128, 128]);
  await page.getByRole("button", { name: "编辑 github", exact: true }).click();
  await dialog.getByRole("button", { name: "恢复默认", exact: true }).click();
  await expect(dialog.locator("img")).toHaveAttribute(
    "src",
    "/images/plugins/github.svg",
  );
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(
    page.locator('article img[data-plugin-icon="github"]'),
  ).toHaveAttribute("src", "/images/plugins/github.svg");
  expect(servers.github?.presentation).toEqual({ display_name: "Engineering" });

  await page
    .getByRole("button", { name: "添加 MCP 插件", exact: true })
    .click();
  await dialog.getByRole("textbox").fill(
    JSON.stringify({
      "acme-crm": {
        enabled: false,
        type: "http",
        url: "https://example.test/crm",
        description: "企业内部客户关系管理",
      },
    }),
  );
  await dialog.locator('input[type="file"]').setInputFiles(file);
  await expect(dialog.locator("img")).toHaveAttribute(
    "src",
    /^data:image\/png;base64,/,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    dialog.getByRole("button", { name: "保存", exact: true }),
  ).toBeInViewport();
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(servers["acme-crm"]?.presentation?.icon).toMatch(
    /^data:image\/png;base64,/,
  );
  expect(writes).toBe(3);
  expect(errors).toEqual([]);
});

test("invalid or oversized uploads do not replace the existing icon", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.route("**/api/mcp/config", (route) =>
    route.fulfill({
      json: {
        mcp_servers: {
          github: {
            capability: {
              id: "fixture-github",
              plugin_id: "github",
              version: "1",
            },
            enabled: false,
            description: "GitHub",
            type: "http",
            url: "https://example.test/github",
          },
        },
      },
    }),
  );
  await page.goto("/workspace/capabilities");
  await page.getByRole("button", { name: "Edit github", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const input = dialog.locator('input[type="file"]');
  await input.setInputFiles({
    name: "bad.svg",
    mimeType: "image/svg+xml",
    buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'),
  });
  await expect(dialog.getByRole("alert")).toContainText("Choose a PNG");
  await input.setInputFiles({
    name: "large.png",
    mimeType: "image/png",
    buffer: Buffer.alloc(2 * 1024 * 1024 + 1),
  });
  await expect(dialog.getByRole("alert")).toContainText("2 MB or smaller");
  await input.setInputFiles({
    name: "fake.png",
    mimeType: "image/png",
    buffer: Buffer.from("not an image"),
  });
  await expect(dialog.getByRole("alert")).toContainText("Cannot read");
  await expect(dialog.locator("img")).toHaveAttribute(
    "src",
    "/images/plugins/github.svg",
  );
  await expect(
    dialog.getByRole("button", { name: "Save", exact: true }),
  ).toBeEnabled();
  for (const mimeType of ["image/jpeg", "image/webp"]) {
    await input.setInputFiles(await sampleImage(page, mimeType));
    await expect(dialog.locator("img")).toHaveAttribute(
      "src",
      /^data:image\/png;base64,/,
    );
    await dialog
      .getByRole("button", { name: "Restore default", exact: true })
      .click();
    await expect(dialog.locator("img")).toHaveAttribute(
      "src",
      "/images/plugins/github.svg",
    );
  }
});

test("a custom MCP name does not impersonate a catalog brand in rows or editing", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.route("**/api/mcp/config", (route) =>
    route.fulfill({
      json: {
        mcp_servers: {
          github: {
            enabled: false,
            description: "Private connection without provider metadata",
            type: "http",
            url: "https://example.test/private",
          },
        },
      },
    }),
  );
  await page.goto("/workspace/capabilities");
  const row = page
    .locator("article")
    .filter({ hasText: "Private connection without provider metadata" });
  await expect(row).toBeVisible();
  await expect(row.locator("img")).toHaveCount(0);
  await row.getByRole("button", { name: "Edit github", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").locator("img")).toHaveCount(0);
});
