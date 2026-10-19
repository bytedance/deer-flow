import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

async function mockConnections(page: Page) {
  mockLangGraphAPI(page);
  const state = { platform: false, personal: false, role: "admin" };
  const writes: { scope: string; body: unknown }[] = [];
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: state.role,
        email: `${state.role}@example.test`,
        system_role: state.role,
        needs_setup: false,
      },
    }),
  );
  await page.route("**/api/capabilities/installations/mcp?scope=all", (route) =>
    route.fulfill({
      json: {
        can_manage: state.role === "admin",
        items: [
          {
            id: "shared-github",
            plugin_id: null,
            adapter: "mcp",
            name: "github",
            reference: "github",
            description: "Shared repository tools",
            installed: true,
            enabled: state.platform,
            scope: "deployment",
            auth_status: "configured",
          },
        ],
      },
    }),
  );
  for (const [scope, endpoint] of [
    ["platform", "/api/mcp/config"],
    ["personal", "/api/mcp/personal/config"],
  ] as const) {
    await page.route(`**${endpoint}`, (route) => {
      if (route.request().method() === "PATCH") {
        const body = route.request().postDataJSON() as {
          server_name: string;
          enabled: boolean;
        };
        writes.push({ scope, body });
        state[scope] = body.enabled;
      }
      return route.fulfill({
        json: {
          mcp_servers: {
            github: {
              enabled: state[scope],
              type: "http",
              url: "https://example.test/mcp",
              description:
                scope === "platform"
                  ? "Shared repository tools"
                  : "Personal repository tools",
            },
          },
        },
      });
    });
  }
  return { state, writes };
}

test("administrators toggle shared MCP globally without changing a same-named personal connection", async ({
  page,
}, testInfo) => {
  const { state, writes } = await mockConnections(page);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/workspace/capabilities");
  await page
    .getByRole("textbox", { name: "Search plugins by name or purpose" })
    .fill("github");
  const platform = page.getByRole("region", {
    name: "Platform provided",
    exact: true,
  });
  const sharedSwitch = page.getByRole("switch", {
    name: "Enabled github (Platform provided)",
    exact: true,
  });
  const personalSwitch = page.getByRole("switch", {
    name: "Enabled github (My plugins)",
    exact: true,
  });
  await expect(platform.getByText("github", { exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("platform-mcp-controls.png"),
    fullPage: true,
  });
  await expect(sharedSwitch).not.toBeChecked();
  await sharedSwitch.click();
  await expect(sharedSwitch).toBeChecked();
  await expect(personalSwitch).not.toBeChecked();
  await personalSwitch.click();
  await expect(personalSwitch).toBeChecked();
  await expect(sharedSwitch).toBeChecked();
  await sharedSwitch.click();
  await expect(sharedSwitch).not.toBeChecked();
  await expect(personalSwitch).toBeChecked();
  expect(writes).toEqual([
    { scope: "platform", body: { server_name: "github", enabled: true } },
    { scope: "personal", body: { server_name: "github", enabled: true } },
    { scope: "platform", body: { server_name: "github", enabled: false } },
  ]);

  state.role = "user";
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect(platform.getByRole("switch")).toHaveCount(0);
  await expect(
    platform.getByRole("button", { name: /Add MCP|Edit |Delete / }),
  ).toHaveCount(0);
  await expect(
    platform.locator("article").filter({ hasText: "github" }),
  ).toContainText("Disabled");
  await expect(personalSwitch).toBeEnabled();
  await page
    .getByRole("textbox", { name: "Search plugins by name or purpose" })
    .fill("github");
  await page.screenshot({
    path: testInfo.outputPath("platform-mcp-member.png"),
    fullPage: true,
  });
  expect(writes).toHaveLength(3);
});

test("a rejected platform toggle keeps the stored state and reports the error", async ({
  page,
}) => {
  await mockConnections(page);
  let finishRequest!: () => void;
  await page.route("**/api/mcp/config", async (route) => {
    if (route.request().method() === "GET") return route.fallback();
    await new Promise<void>((resolve) => {
      finishRequest = resolve;
    });
    await route.fulfill({
      status: 403,
      json: { detail: "Administrator access required" },
    });
  });
  await page.goto("/workspace/capabilities");
  const toggle = page
    .getByRole("region", { name: "Platform provided", exact: true })
    .getByRole("switch", {
      name: "Enabled github (Platform provided)",
      exact: true,
    });
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(toggle).toBeDisabled();
  await expect(toggle).not.toBeChecked();
  finishRequest();
  await expect(
    page.getByText("Administrator access required", { exact: true }),
  ).toBeVisible();
  await expect(toggle).toBeEnabled();
  await expect(toggle).not.toBeChecked();
});

test("administrators add, edit and delete shared MCP using the existing editor", async ({
  page,
}) => {
  const { writes } = await mockConnections(page);
  const servers: Record<string, Record<string, unknown>> = {
    github: {
      enabled: false,
      type: "http",
      url: "https://example.test/mcp",
      headers: { Authorization: "***" },
      routing: { mode: "prefer" },
    },
  };
  const changes: { method: string; body: unknown }[] = [];
  await page.route("**/api/mcp/config**", async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname;
    if (method === "POST") {
      const body = request.postDataJSON() as { mcp_servers: typeof servers };
      Object.assign(servers, body.mcp_servers);
      changes.push({ method, body });
    } else if (method === "PUT") {
      const body = request.postDataJSON() as {
        server_name: string;
        server: Record<string, unknown>;
      };
      servers[body.server_name] = body.server;
      changes.push({ method, body });
    } else if (method === "DELETE") {
      delete servers[decodeURIComponent(path.split("/").pop()!)];
      changes.push({ method, body: path });
    }
    await route.fulfill({ json: { mcp_servers: servers } });
  });
  await page.goto("/workspace/capabilities");
  const platform = page.getByRole("region", {
    name: "Platform provided",
    exact: true,
  });
  const personal = page.getByRole("region", {
    name: "My plugins",
    exact: true,
  });
  await platform
    .getByRole("button", {
      name: "Edit github (Platform provided)",
      exact: true,
    })
    .click();
  const dialog = page.getByRole("dialog");
  const definition = JSON.parse(
    await dialog.getByRole("textbox").inputValue(),
  ) as { mcpServers: typeof servers };
  expect(definition.mcpServers.github).toEqual(servers.github);
  definition.mcpServers.github!.description = "Updated shared tools";
  await dialog.getByRole("textbox").fill(JSON.stringify(definition));
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(
    platform.getByText("Updated shared tools", { exact: true }),
  ).toBeVisible();
  expect(servers.github?.headers).toEqual({ Authorization: "***" });
  expect(servers.github?.routing).toEqual({ mode: "prefer" });
  await platform
    .getByRole("button", {
      name: "Add MCP plugin (Platform provided)",
      exact: true,
    })
    .click();
  const added = {
    description: "Team tools",
    enabled: false,
    type: "http",
    url: "https://example.test/new",
  };
  await dialog
    .getByRole("textbox")
    .fill(JSON.stringify({ "team-tools": added }));
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(
    platform.getByRole("button", {
      name: "Edit team-tools (Platform provided)",
      exact: true,
    }),
  ).toBeVisible();
  await platform
    .getByRole("button", {
      name: "Delete github (Platform provided)",
      exact: true,
    })
    .click();
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(
    platform.getByRole("button", {
      name: "Edit github (Platform provided)",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    personal.getByRole("button", {
      name: "Edit github (My plugins)",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    personal.getByRole("switch", {
      name: "Enabled github (My plugins)",
      exact: true,
    }),
  ).not.toBeChecked();
  expect(changes).toEqual([
    {
      method: "PUT",
      body: { server_name: "github", server: definition.mcpServers.github },
    },
    { method: "POST", body: { mcp_servers: { "team-tools": added } } },
    { method: "DELETE", body: "/api/mcp/config/servers/github" },
  ]);
  expect(writes).toEqual([]);
});
