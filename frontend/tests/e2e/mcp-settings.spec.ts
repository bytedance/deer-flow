import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const { viewport, name } of [
  { viewport: { width: 500, height: 280 }, name: "github" },
  {
    viewport: { width: 844, height: 390 },
    name: `github-${"long-server-name-".repeat(30)}`,
  },
]) {
  test(`MCP dialog actions remain reachable during fallback scrolling at ${viewport.width}x${viewport.height}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    mockLangGraphAPI(page);
    const server = { enabled: false, command: "npx", args: ["example"] };
    await page.route("**/api/mcp/config", (route) =>
      route.fulfill({ json: { mcp_servers: { [name]: server } } }),
    );
    await page.goto("/workspace/capabilities");

    for (const mode of ["edit", "add"] as const) {
      await page
        .getByRole("button", {
          name: mode === "edit" ? `Edit ${name}` : "Add MCP plugin",
          exact: true,
        })
        .click();
      const dialog = page.getByRole("dialog");
      const textbox = dialog.getByRole("textbox");
      if (mode === "add") {
        await textbox.fill(JSON.stringify({ mcpServers: { [name]: server } }));
        // The duplicate-name validation message also contains user text.
        await dialog.getByRole("button", { name: "Save", exact: true }).click();
        await expect(dialog.getByRole("alert")).toBeVisible();
      }

      // Find the actual overflowing ancestor, so this also exercises the
      // pre-fix dialog-level fallback rather than assuming a wrapper exists.
      expect(
        await textbox.evaluate((element) => {
          for (
            let parent = element.parentElement;
            parent;
            parent = parent.parentElement
          ) {
            if (
              /auto|scroll/.test(getComputedStyle(parent).overflowY) &&
              parent.scrollHeight > parent.clientHeight
            ) {
              parent.scrollTop = parent.scrollHeight;
              return parent.scrollTop;
            }
          }
          return 0;
        }),
      ).toBeGreaterThan(0);

      const expectActionsVisible = async () => {
        for (const element of [
          dialog,
          dialog.getByRole("heading"),
          dialog.getByRole("button", { name: "Close", exact: true }),
          dialog.getByRole("button", { name: "Save", exact: true }),
          dialog.getByRole("button", { name: "Cancel", exact: true }),
        ]) {
          await expect(element).toBeInViewport({ ratio: 1 });
        }
      };
      await expectActionsVisible();
      await textbox.fill("{invalid");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await dialog.getByRole("alert").scrollIntoViewIfNeeded();
      await expectActionsVisible();
      await page.screenshot({
        path: testInfo.outputPath(`${mode}-fallback.png`),
      });
      await dialog
        .getByRole("button", {
          name: mode === "edit" ? "Close" : "Cancel",
          exact: true,
        })
        .click();
      await expect(dialog).toBeHidden();
    }
  });
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 667 },
  { width: 844, height: 390 },
]) {
  test(`long MCP definitions stay usable at ${viewport.width}x${viewport.height}`, async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize(viewport);
    mockLangGraphAPI(page);
    const server = {
      enabled: false,
      description: "GitHub MCP server for repository operations",
      type: "stdio",
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-github"],
      env: Object.fromEntries(
        Array.from({ length: 60 }, (_, index) => [`TEST_${index}`, "example"]),
      ),
    };
    await page.route("**/api/mcp/config", (route) =>
      route.fulfill({ json: { mcp_servers: { github: server } } }),
    );
    await page.goto("/workspace/capabilities");

    for (const mode of ["edit", "add"] as const) {
      await page
        .getByRole("button", {
          name: mode === "edit" ? "Edit github" : "Add MCP plugin",
          exact: true,
        })
        .click();
      const dialog = page.getByRole("dialog");
      const textbox = dialog.getByRole("textbox");
      if (mode === "add") {
        await textbox.fill(
          JSON.stringify({ mcpServers: { github: server } }, null, 2),
        );
      }
      const expectWithinViewport = async () => {
        // The icon editor adds body content on short screens. Scroll the JSON
        // editor into view while keeping the pinned heading/actions visible.
        await textbox.evaluate((element) =>
          element.scrollIntoView({ block: "center" }),
        );
        for (const element of [
          dialog,
          dialog.getByRole("heading"),
          textbox,
          dialog.getByRole("button", { name: "Cancel", exact: true }),
          dialog.getByRole("button", { name: "Save", exact: true }),
          dialog.getByRole("button", { name: "Close", exact: true }),
        ]) {
          await expect(element).toBeInViewport({ ratio: 1 });
        }
      };
      await expectWithinViewport();
      expect(
        await textbox.evaluate(
          (element) => element.scrollHeight > element.clientHeight,
        ),
      ).toBe(true);
      await textbox.hover();
      await page.mouse.wheel(0, 10000);
      await expect
        .poll(() => textbox.evaluate((element) => element.scrollTop))
        .toBeGreaterThan(0);
      await expectWithinViewport();
      await page.screenshot({ path: testInfo.outputPath(`${mode}.png`) });

      await textbox.fill("{invalid");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog.getByRole("alert")).toBeVisible();
      await expectWithinViewport();
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      await expect(dialog).toBeHidden();
    }
    expect(errors).toEqual([]);
  });
}

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

    await page.goto("/workspace/capabilities");

    const settingsDialog = page;
    await expect(page).toHaveURL(/workspace\/capabilities$/);
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
