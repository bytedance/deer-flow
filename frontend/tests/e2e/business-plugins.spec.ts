import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const plugin of [
  {
    id: "dingtalk",
    name: "DingTalk group notifications",
    fields: { access_token: "fixture-token", sign_secret: "fixture-secret" },
  },
  {
    id: "wecom",
    name: "WeCom group notifications",
    fields: { webhook_key: "fixture-key" },
  },
  {
    id: "hubspot",
    name: "HubSpot CRM",
    fields: { access_token: "fixture-token" },
  },
]) {
  test(`${plugin.id} configures bundled tools without a server URL`, async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let submission: Record<string, unknown> | undefined;
    let configured = false;
    const connectionName = `team-${plugin.id}`;
    await page.route("**/api/mcp/config", (route) =>
      route.fulfill({
        json: {
          mcp_servers: configured
            ? {
                [connectionName]: {
                  enabled: true,
                  type: "stdio",
                  command: "python",
                  env: { TOKEN: "***" },
                  capability: {
                    id: `fixture-${plugin.id}`,
                    plugin_id: plugin.id,
                    version: "2",
                  },
                },
              }
            : {},
        },
      }),
    );
    await page.route("**/api/capabilities/installations", (route) => {
      submission = route.request().postDataJSON() as Record<string, unknown>;
      configured = true;
      return route.fulfill({ json: { items: [], can_manage: true } });
    });
    await page.goto(`/workspace/capabilities?plugin=${plugin.id}`);
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: plugin.name }),
    ).toBeVisible();
    await expect(dialog.getByLabel("Server URL")).toHaveCount(0);
    await dialog.getByLabel("Connection name").fill(connectionName);
    for (const [key, value] of Object.entries(plugin.fields)) {
      const field = dialog.locator(`#plugin-field-${key}`);
      await expect(field).toHaveAttribute("type", "password");
      await field.fill(value);
    }
    const screenshotDirectory = process.env.CAPABILITY_SCREENSHOT_DIR;
    if (plugin.id === "hubspot" && screenshotDirectory) {
      await mkdir(screenshotDirectory, { recursive: true });
      await page.screenshot({
        path: path.join(screenshotDirectory, "hubspot-configuration-en.png"),
      });
    }
    await dialog.getByRole("button", { name: "Save configuration" }).click();
    await expect(dialog).toHaveCount(0);
    expect(submission).toEqual({
      plugin_id: plugin.id,
      name: connectionName,
      configuration: plugin.fields,
    });
    await expect(
      page.locator("article").filter({ hasText: connectionName }),
    ).toHaveCount(1);
    expect(errors).toEqual([]);
  });
}

test("rejected credentials remain editable and are not marked configured", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.route("**/api/capabilities/installations", (route) =>
    route.fulfill({
      status: 422,
      json: { detail: "Invalid credential: access_token" },
    }),
  );
  await page.goto("/workspace/capabilities?plugin=hubspot");
  const dialog = page.getByRole("dialog");
  await dialog.locator("#plugin-field-access_token").fill("invalid value");
  await dialog.getByRole("button", { name: "Save configuration" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Save configuration" }),
  ).toBeEnabled();
  await expect(dialog.locator("#plugin-field-access_token")).toHaveValue(
    "invalid value",
  );
});

test("ordinary users see each shared connection once and cannot configure credentials", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "member",
        email: "member@example.test",
        system_role: "user",
        needs_setup: false,
      },
    }),
  );
  const connection = {
    id: "shared-hubspot",
    plugin_id: "hubspot",
    adapter: "mcp",
    name: "Team CRM",
    reference: "team-crm",
    installed: true,
    enabled: true,
    auth_status: "configured",
    health: "unknown",
    scope: "deployment",
  };
  // Both adapters project the same MCP installation, not a second account.
  for (const adapter of ["mcp", "business"]) {
    await page.route(`**/api/capabilities/installations/${adapter}`, (route) =>
      route.fulfill({ json: { items: [connection], can_manage: false } }),
    );
  }
  await page.goto("/workspace/capabilities");
  // The local preview starts with an SSR admin. Use the real account-refresh
  // event to apply the mocked ordinary-user session after hydration.
  await expect(
    page.getByRole("textbox", { name: "Search plugins by name or purpose" }),
  ).toBeEnabled();
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect(
    page.locator("article").filter({ hasText: "Team CRM" }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "Add MCP plugin" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Configure WeCom group notifications",
      exact: true,
    })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("#plugin-field-webhook_key")).toBeDisabled();
  await expect(dialog.locator("#plugin-field-webhook_key")).toHaveValue("");
  await expect(
    dialog.getByRole("button", { name: "Save configuration" }),
  ).toBeDisabled();
});
