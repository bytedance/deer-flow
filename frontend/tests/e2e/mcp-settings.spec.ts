import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("MCP server settings", () => {
  test("edits one server without dropping advanced fields or siblings", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    let servers = {
      local: {
        enabled: true,
        description: "Local tools",
        command: "uvx",
        args: ["local-tools"],
      },
      remote: {
        enabled: false,
        description: "Remote tools",
        type: "http",
        url: "https://example.test/mcp",
        headers: { "X-API-Key": "***" },
        routing: { mode: "prefer" },
      },
    };
    let submittedUpdate:
      | { server_name: string; server: (typeof servers)["remote"] }
      | undefined;

    await page.route("**/api/mcp/config", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ mcp_servers: servers }),
      });
    });
    await page.route("**/api/mcp/config/server", async (route) => {
      if (route.request().method() !== "PUT") {
        await route.fallback();
        return;
      }
      submittedUpdate = route
        .request()
        .postDataJSON() as typeof submittedUpdate;
      servers = {
        ...servers,
        [submittedUpdate!.server_name]: submittedUpdate!.server,
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ mcp_servers: servers }),
      });
    });

    await page.goto("/workspace/chats/new?settings=tools");

    const settingsDialog = page.getByRole("dialog", { name: "Settings" });
    await expect(settingsDialog).toBeVisible();
    await settingsDialog.getByRole("button", { name: "Edit remote" }).click();

    const editor = page.getByRole("dialog", { name: "Edit MCP server" });
    const definitionBox = editor.getByRole("textbox");
    const definition = JSON.parse(await definitionBox.inputValue()) as {
      mcpServers: typeof servers;
    };
    definition.mcpServers.remote.description = "Updated remote tools";
    await definitionBox.fill(JSON.stringify(definition));
    await editor.getByRole("button", { name: "Save" }).click();

    await expect(editor).toBeHidden();
    await expect(
      settingsDialog.getByText("Updated remote tools"),
    ).toBeVisible();
    expect(submittedUpdate).toEqual({
      server_name: "remote",
      server: {
        enabled: false,
        description: "Updated remote tools",
        type: "http",
        url: "https://example.test/mcp",
        headers: { "X-API-Key": "***" },
        routing: { mode: "prefer" },
      },
    });
  });
});
