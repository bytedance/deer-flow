import { spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir } from "node:fs/promises";
import { createServer } from "node:net";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

let gateway: ChildProcess;
let gatewayURL: string;
test.beforeAll(async ({ request }) => {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const address = probe.address();
  if (!address || typeof address === "string")
    throw new Error("Missing test port");
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  gatewayURL = `http://127.0.0.1:${address.port}`;
  const backend = path.resolve(process.cwd(), "../backend");
  gateway = spawn(
    path.join(backend, ".venv/bin/python"),
    [
      "-m",
      "extension_test_fixtures.bookmark_plugin_gateway",
      String(address.port),
    ],
    { cwd: backend, stdio: "pipe" },
  );
  let diagnostics = "";
  gateway.stderr?.on("data", (chunk) => {
    diagnostics += String(chunk);
  });
  await expect
    .poll(
      async () => {
        if (gateway.exitCode !== null) throw new Error(diagnostics);
        return request
          .get(`${gatewayURL}/api/plugins`)
          .then((r) => r.status())
          .catch(() => 0);
      },
      { timeout: 20_000 },
    )
    .toBe(200);
});
test.afterAll(async () => {
  if (gateway?.exitCode === null) {
    const exited = new Promise<void>((resolve) =>
      gateway.once("exit", () => resolve()),
    );
    gateway.kill("SIGTERM");
    await exited;
  }
});

for (const source of ["default", "custom-toolbar", "custom-sidebar"]) {
  test(`bookmark package (${source}): save, reopen original agent, tool lookup, isolation and delete`, async ({
    page,
    request,
  }) => {
    test.setTimeout(90_000);
    const frontendURL =
      process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
    const backendBase = process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
    const backendURL = new URL(backendBase || frontendURL, frontendURL);
    await page.context().addCookies([
      {
        name: "plugin_test_session",
        value: "synthetic",
        url: backendURL.origin,
      },
    ]);
    await page.setViewportSize({ width: 1360, height: 1050 });
    const agentName = source === "default" ? undefined : "researcher";
    const conversationURL = agentName
      ? `/workspace/agents/${agentName}/chats/${MOCK_THREAD_ID}`
      : `/workspace/chats/${MOCK_THREAD_ID}`;
    mockLangGraphAPI(page, {
      agents: agentName
        ? [{ name: agentName, description: "Research assistant" }]
        : [],
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Plugin architecture",
          agent_name: agentName,
          messages: [
            {
              id: "u",
              type: "human",
              content: "What should the plugin host provide?",
            },
            {
              id: "a",
              type: "ai",
              content:
                "ORCHID plugin design: one package provides a custom page, backend actions and model tools. Deployment owns installation and activation.",
              additional_kwargs: { reasoning_content: "PRIVATE REASONING" },
            },
            {
              id: "hidden",
              type: "ai",
              content: "HIDDEN ANSWER",
              additional_kwargs: { hide_from_ui: true },
            },
          ],
        },
      ],
    });
    let savedPayload: Record<string, unknown> | undefined;
    const moduleRequests: string[] = [];
    await page.route("**/api/plugins**", async (route) => {
      const url = new URL(route.request().url());
      const cors = {
        "access-control-allow-origin": new URL(frontendURL).origin,
        "access-control-allow-credentials": "true",
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers":
          "content-type, x-deerflow-plugin-viewer, x-csrf-token",
      };
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: cors });
        return;
      }
      if (url.pathname.includes("/modules/")) {
        moduleRequests.push(url.href);
        if (
          !(await route.request().allHeaders()).cookie?.includes(
            "plugin_test_session=synthetic",
          )
        ) {
          await route.fulfill({ status: 401, headers: cors });
          return;
        }
      }
      if (url.pathname.endsWith("/actions/save"))
        savedPayload = route.request().postDataJSON();
      const response = await route.fetch({
        url: gatewayURL + url.pathname.slice(url.pathname.indexOf("/api/")),
        headers: {
          ...route.request().headers(),
          "x-test-user": "alice",
          "x-test-role": "admin",
        },
      });
      await route.fulfill({
        response,
        headers: { ...response.headers(), ...cors },
      });
    });
    await page.goto(conversationURL);
    const libraryURL = "/workspace/extensions/community.bookmarks/library";
    const libraryLink = page.getByRole("link", {
      name: "My bookmarks",
      exact: true,
    });
    await expect(libraryLink).toHaveAttribute("href", libraryURL);
    expect(moduleRequests).toHaveLength(1);
    const modulePrefix = new URL(
      `${backendBase.replace(/\/+$/, "")}/api/plugins/modules/`,
      frontendURL,
    ).href;
    expect(moduleRequests[0]?.startsWith(modulePrefix)).toBe(true);
    if (source === "custom-sidebar") {
      await page
        .locator(`a[data-sidebar="menu-button"][href="${conversationURL}"]`)
        .locator("xpath=..")
        .getByRole("button", { name: "More" })
        .click();
      await page
        .getByRole("menuitem", { name: "Bookmarks", exact: true })
        .hover();
    } else {
      await page
        .getByRole("button", { name: "Bookmarks", exact: true })
        .click();
    }
    await page
      .getByRole("menuitem", { name: "Save last answer", exact: true })
      .click();
    await expect(
      page.getByText("Saved. Open My bookmarks in the sidebar.", {
        exact: true,
      }),
    ).toBeVisible();
    expect(savedPayload?.message_id).toBe("a");
    expect(JSON.stringify(savedPayload)).not.toContain("PRIVATE");
    expect(JSON.stringify(savedPayload)).not.toContain("HIDDEN");
    await page.goto("/workspace/capabilities?tab=extensions");
    await expect(page.getByRole("switch")).toHaveCount(0);
    if (process.env.EXTENSION_SCREENSHOT_DIR) {
      await mkdir(process.env.EXTENSION_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({
        path: path.join(
          process.env.EXTENSION_SCREENSHOT_DIR,
          "bookmarks-directory.png",
        ),
        fullPage: true,
      });
    }
    await page
      .getByRole("button", { name: "View 会话书签 / Bookmarks", exact: true })
      .click();
    await expect(
      page.getByRole("searchbox", { name: "Search bookmarks" }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Enabled · Managed by your administrator", {
        exact: true,
      }),
    ).toBeVisible();
    await libraryLink.click();
    await expect(page).toHaveURL(new RegExp(`${libraryURL}$`));
    await expect(
      page.getByRole("heading", { name: "My bookmarks", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Keep answers worth returning to", { exact: true }),
    ).toBeVisible();
    const name = page.getByRole("textbox", {
      name: "Bookmark name",
      exact: true,
    });
    await expect(name).toBeVisible();
    await name.fill("Plugin interface decisions");
    await page.getByRole("button", { name: "Save name", exact: true }).click();
    await page.reload();
    await expect(name).toHaveValue("Plugin interface decisions");
    await page
      .getByRole("searchbox", { name: "Search bookmarks", exact: true })
      .fill("ORCHID");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByText(/1 saved/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Search", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Open conversation", exact: true })
      .click();
    await expect(page).toHaveURL(new RegExp(`${conversationURL}$`));
    // Verify continuing the reopened conversation still invokes its originating agent.
    const runRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" && request.url().includes("/runs/stream"),
    );
    await page.getByRole("textbox").fill("Continue this conversation");
    await page.getByRole("textbox").press("Enter");
    const runPayload = (await runRequest).postDataJSON();
    expect(runPayload.assistant_id).toBe(agentName ?? "lead_agent");
    if (agentName) expect(runPayload.context.agent_name).toBe(agentName);
    await libraryLink.click();
    await expect(name).toHaveValue("Plugin interface decisions");
    await expect(page.getByRole("switch")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Save plugin settings" }),
    ).toHaveCount(0);
    const modelResponse = await request.post(
      `${gatewayURL}/test/model-search`,
      {
        headers: { "x-test-user": "alice" },
        data: { query: "ORCHID" },
      },
    );
    const modelResult = await modelResponse.json();
    expect(modelResult.tool).toContain("search_bookmarks");
    const items = JSON.parse(modelResult.content).items;
    expect(items).toHaveLength(1);
    expect(items[0].label).toBe("Plugin interface decisions");
    const bob = await request.post(`${gatewayURL}/test/model-search`, {
      headers: { "x-test-user": "bob" },
      data: { query: "ORCHID" },
    });
    expect(JSON.parse((await bob.json()).content).items).toEqual([]);
    expect(
      (
        await request.post(
          `${gatewayURL}/api/plugins/community.bookmarks/actions/delete`,
          { headers: { "x-test-user": "bob" }, data: { id: items[0].id } },
        )
      ).status(),
    ).toBe(422);
    expect(
      (
        await request.patch(`${gatewayURL}/api/plugins/community.bookmarks`, {
          headers: { "x-test-role": "admin" },
          data: { revision: "fake", changes: { enabled: false } },
        })
      ).status(),
    ).toBe(404);
    if (process.env.EXTENSION_SCREENSHOT_DIR)
      await page.screenshot({
        path: path.join(
          process.env.EXTENSION_SCREENSHOT_DIR,
          "bookmarks-detail.png",
        ),
        fullPage: true,
      });
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await page
      .getByRole("button", { name: "Confirm delete", exact: true })
      .click();
    await expect(
      page.getByText("No matching bookmarks", { exact: true }),
    ).toBeVisible();
    // A refreshed deployment snapshot removes both the entry and direct-page access.
    await page.route("**/api/plugins", async (route) => {
      const response = await request.get(`${gatewayURL}/api/plugins`);
      const entries = await response.json();
      await route.fulfill({
        json: entries.map((entry: { settings: Record<string, unknown> }) => ({
          ...entry,
          settings: { ...entry.settings, enabled: false },
        })),
      });
    });
    await page.reload();
    await expect(libraryLink).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Extension page unavailable" }),
    ).toBeVisible();
    await expect(
      page.getByRole("searchbox", { name: "Search bookmarks" }),
    ).toHaveCount(0);
  });
}

for (const brokenFactory of [
  "throw new Error('broken plugin');",
  "return { actions: undefined };",
  "return { label: 'Broken', icon: 'bookmark', actions: [{ id: 'broken', label: 'Broken', icon: 'bookmark', available: async () => { throw new Error('rejected availability'); }, execute: async () => {} }] };",
]) {
  test(`a broken plugin action factory is isolated: ${brokenFactory}`, async ({
    page,
    baseURL,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Healthy conversation",
          messages: [
            {
              id: "answer",
              type: "ai",
              content: "The conversation is still usable.",
            },
          ],
        },
      ],
    });
    const code = {
      broken: `export default { apiVersion: 1, module: 'broken', conversationActions() { ${brokenFactory} } };`,
      healthy: `export default { apiVersion: 1, module: 'healthy', conversationActions() { return { label: 'Healthy actions', icon: 'bookmark', actions: [{ id: 'test', label: 'Run healthy action', icon: 'bookmark', available: () => true, execute: async (_context, services) => services.showMessage('Healthy action completed.') }] }; } };`,
    };
    const entries = Object.entries(code).map(([module, source]) => ({
      namespace: `test.${module}`,
      module,
      title: module,
      description: "",
      settings: { enabled: true },
      entry: `/api/plugins/modules/${module}/${createHash("sha256").update(source).digest("hex")}.mjs`,
    }));
    await page.route("**/api/plugins**", async (route) => {
      const url = new URL(route.request().url());
      const headers = {
        "access-control-allow-origin": new URL(baseURL!).origin,
        "access-control-allow-credentials": "true",
      };
      if (url.pathname.endsWith("/api/plugins"))
        return route.fulfill({ json: entries, headers });
      const entry = entries.find((item) => url.pathname.endsWith(item.entry));
      if (!entry) return route.fulfill({ status: 404, headers });
      return route.fulfill({
        body: code[entry.module as keyof typeof code],
        contentType: "text/javascript",
        headers,
      });
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(
      page.getByText("The conversation is still usable.", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Healthy actions", exact: true })
      .click();
    await page
      .getByRole("menuitem", { name: "Run healthy action", exact: true })
      .click();
    await expect(
      page.getByText("Healthy action completed.", { exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
}

for (const locale of ["en-US", "zh-CN"]) {
  test(`extension host uses ${locale} copy and its own search label`, async ({
    page,
    baseURL,
  }) => {
    const zh = locale === "zh-CN";
    mockLangGraphAPI(page);
    await page
      .context()
      .addCookies([{ name: "locale", value: locale, url: baseURL! }]);
    await page.goto("/workspace/capabilities?tab=extensions");
    await expect(
      page.getByRole("tab", {
        name: zh ? "扩展插件" : "Extensions",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByPlaceholder(
        zh ? "按名称或用途搜索扩展" : "Search extensions by name or purpose",
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: zh
          ? "重新加载扩展（刷新页面）"
          : "Reload extensions (refresh page)",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByText(
        zh ? "没有匹配的已安装扩展。" : "No matching installed extensions.",
        { exact: true },
      ),
    ).toBeVisible();
    await page.goto("/workspace/extensions/missing.plugin/library");
    await expect(
      page.getByRole("heading", {
        name: zh ? "扩展页面不可用" : "Extension page unavailable",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: zh ? "查看扩展" : "View extensions" }),
    ).toBeVisible();
  });
}

test("unregistered plugin pages stay unavailable", async ({ page }) => {
  mockLangGraphAPI(page);
  await page.goto("/workspace/extensions/missing.plugin/library");
  await expect(
    page.getByRole("heading", { name: "Extension page unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByRole("searchbox", { name: "Search bookmarks" }),
  ).toHaveCount(0);
});
