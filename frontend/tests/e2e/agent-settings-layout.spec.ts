import { expect, test, type Locator } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const description =
  "A general-purpose worker for independent analysis. " +
  "Investigate the delegated question, check the evidence, and report findings to the caller. ".repeat(
    15,
  );

async function expectInsideViewport(element: Locator) {
  await expect(element).toBeVisible();
  const bounds = await element.boundingBox();
  const viewport = element.page().viewportSize()!;
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height);
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 640 },
]) {
  test(`agent settings remain usable at ${viewport.width}x${viewport.height}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    const agent = {
      name: "test-agent",
      model: "test-model",
      thinking_enabled: true,
      reasoning_effort: "high",
      allowed_subagents: null,
    };
    mockLangGraphAPI(page, { agents: [agent] });
    await page.route("**/api/models", (route) =>
      route.fulfill({
        json: {
          models: [
            {
              name: "test-model",
              display_name: "Test model",
              supports_thinking: true,
              supports_reasoning_effort: true,
            },
          ],
        },
      }),
    );
    await page.route("**/api/subagents", (route) =>
      route.fulfill({
        json: {
          subagents: [
            { name: "general-purpose", description, enabled: true },
            { name: "bash", description: "Run shell commands.", enabled: true },
          ],
        },
      }),
    );
    let saved: Record<string, unknown> | undefined;
    await page.route("**/api/agents/test-agent", (route) => {
      if (route.request().method() === "PUT") {
        saved = route.request().postDataJSON() as Record<string, unknown>;
        return route.fulfill({ json: { ...agent, ...saved } });
      }
      return route.fulfill({ json: agent });
    });
    await page.goto("/workspace/agents");
    await page.getByTitle("Agent settings", { exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox").last().click();
    await page
      .getByRole("option", { name: "Selected subagents", exact: true })
      .click();
    await expectInsideViewport(dialog);
    await expectInsideViewport(
      dialog.getByRole("heading", { name: "Agent settings" }),
    );
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Close", exact: true }),
    );
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Save", exact: true }),
    );
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    );

    const general = dialog.getByRole("checkbox", {
      name: "general-purpose",
      exact: true,
    });
    await general.check();
    const details = dialog.locator("details").first();
    const summary = details.locator("summary");
    await summary.scrollIntoViewIfNeeded();
    const preview = summary.locator("span").first();
    expect(
      await preview.evaluate(
        (element) => element.getBoundingClientRect().height,
      ),
    ).toBeLessThanOrEqual(32);
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("open", "");
    await expect(details.locator("p")).toHaveText(description);
    await expect(general).toBeChecked();
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Save", exact: true }),
    );
    await page.keyboard.press("Enter");
    await expect(details).not.toHaveAttribute("open", "");
    await dialog.getByRole("checkbox", { name: "bash", exact: true }).check();
    const screenshotPath = testInfo.outputPath("agent-settings.png");
    await page.screenshot({ path: screenshotPath });
    await testInfo.attach("agent-settings", {
      path: screenshotPath,
      contentType: "image/png",
    });
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(dialog).toBeHidden();
    expect(saved?.allowed_subagents).toEqual(["general-purpose", "bash"]);
  });
}
