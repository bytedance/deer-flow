import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

for (const mobile of [false, true]) {
  test(`catalog batch import and searchable picker ${mobile ? "mobile" : "desktop"}`, async ({
    page,
  }, testInfo) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [{ thread_id: MOCK_THREAD_ID }] });
    const models: Record<string, unknown>[] = [];
    const added: string[] = [];
    await page.route("**/api/models", (route) =>
      route.fulfill({
        json: {
          models: models.filter((m) => m.enabled),
          token_usage: { enabled: false },
        },
      }),
    );
    await page.route("**/api/managed-models", (route) =>
      route.fulfill({ json: { models } }),
    );
    await page.route("**/api/managed-models/providers", (route) =>
      route.fulfill({
        json: {
          providers: [
            {
              id: "openai-compatible",
              display_name: "Custom",
              requires_api_key: false,
              custom_endpoint: true,
            },
            {
              id: "openai",
              display_name: "OpenAI",
              requires_api_key: true,
              custom_endpoint: false,
            },
            {
              id: "qwen-cn",
              display_name: "Alibaba Cloud Bailian / Qwen (China)",
              requires_api_key: true,
              custom_endpoint: false,
            },
            {
              id: "doubao",
              display_name: "Volcengine / Doubao (Beijing, API)",
              requires_api_key: true,
              custom_endpoint: false,
            },
          ],
        },
      }),
    );
    await page.route("**/api/managed-models/discover", (route) => {
      expect(route.request().postDataJSON()).toMatchObject({
        provider: "openai-compatible",
        base_url: "https://custom.example/v1",
        api_key: "fixture-key",
      });
      return route.fulfill({
        json: {
          models: [
            { id: "alpha", configured: false },
            { id: "beta", configured: false },
            { id: "no-tools", configured: false },
          ],
          truncated: false,
        },
      });
    });
    await page.route("**/api/managed-models/import", (route) => {
      const body = route.request().postDataJSON() as { model: string };
      added.push(body.model);
      if (body.model === "no-tools")
        return route.fulfill({
          json: { status: "failed", message: "tool_call_missing" },
        });
      const model = {
        name: body.model,
        model: body.model,
        display_name: body.model,
        provider: "OpenAI",
        enabled: true,
        source: "managed",
        revision: "1",
        has_api_key: true,
      };
      models.push(model);
      return route.fulfill({ json: { status: "saved", model } });
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}?settings=models`);
    await page
      .getByRole("button", { name: "Fetch and add models", exact: true })
      .waitFor();
    await page.screenshot({
      path: testInfo.outputPath("entry.png"),
      animations: "disabled",
    });
    await page.getByRole("button", { name: "Add model", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "Add model", exact: true });
    await editor
      .getByRole("combobox", { name: "Provider", exact: true })
      .selectOption("openai-compatible");
    await editor
      .getByLabel("Base URL", { exact: true })
      .fill("https://custom.example/v1");
    await editor
      .getByLabel("API Key", { exact: true })
      .fill("single-model-draft-key");
    await editor.getByLabel("Model ID", { exact: true }).fill("manual-model");
    await expect(editor).toHaveCSS("opacity", "1");
    const singleEndpointBox = (await editor
      .getByLabel("Base URL", { exact: true })
      .boundingBox())!;
    const singleKeyBox = (await editor
      .getByLabel("API Key", { exact: true })
      .boundingBox())!;
    expect(singleEndpointBox.y + singleEndpointBox.height).toBeLessThanOrEqual(
      singleKeyBox.y,
    );
    await editor.screenshot({
      path: testInfo.outputPath("shared-editor.png"),
      animations: "disabled",
    });
    await editor.getByRole("button", { name: "Cancel", exact: true }).click();
    await page
      .getByRole("button", { name: "Fetch and add models", exact: true })
      .click();
    const dialog = page.getByRole("dialog", {
      name: "Fetch and add models",
      exact: true,
    });
    const provider = dialog.getByRole("combobox", {
      name: "Provider",
      exact: true,
    });
    const apiKey = dialog.getByLabel("API Key", { exact: true });
    await expect(apiKey).toHaveValue("");
    await expect(dialog).toHaveCSS("opacity", "1");
    const providerBox = (await provider.boundingBox())!;
    const keyBox = (await apiKey.boundingBox())!;
    const dialogBox = (await dialog.boundingBox())!;
    expect(providerBox.x + providerBox.width).toBeLessThanOrEqual(
      dialogBox.x + dialogBox.width,
    );
    if (!mobile)
      expect(providerBox.x + providerBox.width).toBeLessThanOrEqual(keyBox.x);
    await dialog.screenshot({
      path: testInfo.outputPath("connection.png"),
      animations: "disabled",
    });
    await provider.selectOption("openai-compatible");
    const endpoint = dialog.getByLabel("Base URL", { exact: true });
    await endpoint.fill("https://custom.example/v1");
    await apiKey.fill("fixture-key");
    const endpointBox = (await endpoint.boundingBox())!;
    const customKeyBox = (await apiKey.boundingBox())!;
    expect(endpointBox.y + endpointBox.height).toBeLessThanOrEqual(
      customKeyBox.y,
    );
    await dialog.screenshot({
      path: testInfo.outputPath("custom-connection.png"),
      animations: "disabled",
    });
    await dialog
      .getByRole("button", { name: "Fetch models", exact: true })
      .click();
    await expect(dialog.getByText("alpha", { exact: true })).toBeVisible();
    expect(added).toEqual([]);
    await expect(dialog.getByLabel("API Key", { exact: true })).toBeHidden();
    await dialog.getByRole("button", { name: "Select visible" }).click();
    await dialog.getByRole("button", { name: "Test and add (3)" }).click();
    await expect(dialog.getByText(/did not return a tool call/)).toBeVisible();
    expect(added).toEqual(["alpha", "beta", "no-tools"]);
    await expect(
      dialog.getByRole("button", { name: "Test and add (1)" }),
    ).toBeEnabled();
    await page.screenshot({
      path: testInfo.outputPath("catalog.png"),
      animations: "disabled",
    });
    await dialog.getByRole("button", { name: "Done", exact: true }).click();
    await page.keyboard.press("Escape");
    await page
      .getByRole("button", { name: "alpha", exact: true })
      .first()
      .click();
    const picker = page.getByRole("dialog", { name: "Choose a model" });
    await picker.getByRole("textbox", { name: "Search models…" }).fill("BETA");
    await expect(
      picker.getByRole("button", { name: "beta (beta)", exact: true }),
    ).toBeVisible();
    await expect(
      picker.getByRole("button", { name: "alpha (alpha)", exact: true }),
    ).toHaveCount(0);
    await picker
      .getByRole("button", { name: "beta (beta)", exact: true })
      .click();
    await page
      .getByRole("button", { name: "beta", exact: true })
      .first()
      .click();
    await expect(
      picker.getByRole("group", { name: "Recently used" }),
    ).toBeVisible();
    await expect(picker).toHaveCSS("opacity", "1");
    await page.screenshot({
      path: testInfo.outputPath("picker.png"),
      animations: "disabled",
    });
    const box = await picker.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  });
}

for (const mobile of [false, true]) {
  test(`provider group keyboard order ${mobile ? "mobile" : "desktop"}`, async ({
    page,
  }, testInfo) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [{ thread_id: MOCK_THREAD_ID }] });
    const models = [
      {
        name: "a1",
        model: "a1",
        display_name: "Alpha 1",
        provider: "Provider A",
      },
      {
        name: "b1",
        model: "b1",
        display_name: "Beta 1",
        provider: "Provider B",
      },
      {
        name: "a2",
        model: "a2",
        display_name: "Alpha 2",
        provider: "Provider A",
      },
    ];
    await page.route("**/api/models", (route) =>
      route.fulfill({ json: { models, token_usage: { enabled: false } } }),
    );
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page
      .getByRole("button", { name: "Alpha 1", exact: true })
      .first()
      .click();
    const picker = page.getByRole("dialog", { name: "Choose a model" });
    const options = picker.locator('[data-model-picker-option="true"]');
    await expect(options).toHaveText(["Alpha 1a1", "Alpha 2a2", "Beta 1b1"]);
    await options.nth(0).focus();
    for (const index of [1, 2, 0]) {
      await page.keyboard.press("ArrowDown");
      await expect(options.nth(index)).toBeFocused();
    }
    await page.keyboard.press("ArrowUp");
    await expect(options.nth(2)).toBeFocused();
    await picker.screenshot({
      path: testInfo.outputPath("grouped-picker.png"),
      animations: "disabled",
    });
  });
}
