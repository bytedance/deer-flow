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
    let submittedServers: typeof servers | undefined;

    await page.route("**/api/mcp/config", async (route) => {
      if (route.request().method() === "PUT") {
        const request = route.request().postDataJSON() as {
          mcp_servers: typeof servers;
        };
        submittedServers = request.mcp_servers;
        servers = request.mcp_servers;
      }

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
    expect(submittedServers).toEqual({
      local: {
        enabled: true,
        description: "Local tools",
        command: "uvx",
        args: ["local-tools"],
      },
      remote: {
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
