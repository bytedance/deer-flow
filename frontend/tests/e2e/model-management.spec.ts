import { expect, test } from "@playwright/test";

import type { ManagedModel, SaveModelRequest } from "@/core/models/management";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

test("administrator adds, tests, edits and disables a shared model", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, { threads: [{ thread_id: MOCK_THREAD_ID }] });
  let models: ManagedModel[] = [];
  let probes = 0;
  let catalogReads = 0;
  const saves: SaveModelRequest[] = [];
  await page.route("**/api/models", (route) => {
    catalogReads++;
    return route.fulfill({
      json: {
        models: models.filter((model) => model.enabled),
        token_usage: { enabled: false },
      },
    });
  });
  await page.route("**/api/managed-models", async (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({ json: { models } });
    const body = route.request().postDataJSON() as SaveModelRequest;
    saves.push(body);
    const { api_key, ...config } = body.config;
    models = [
      {
        ...config,
        source: "managed",
        has_api_key:
          api_key === undefined ? (models[0]?.has_api_key ?? false) : !!api_key,
        revision: String(saves.length),
      },
    ];
    await route.fulfill({ json: models[0] });
  });
  await page.route("**/api/managed-models/test", (route) => {
    probes++;
    return route.fulfill({ json: { ok: true, message: "success" } });
  });
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}?settings=models`);
  await page.getByRole("button", { name: "Add model", exact: true }).click();
  await page.getByLabel("Unique name").fill("demo-model");
  await page.getByLabel("Display name").fill("Demo model");
  await page.getByLabel("Base URL").fill("https://example.com/v1");
  await page.getByLabel("Model ID").fill("demo");
  await page.getByLabel("API Key", { exact: true }).fill("demo-key");
  await page
    .getByRole("button", { name: "Test connection", exact: true })
    .click();
  await expect(
    page.getByText("Streaming and tool-call test passed."),
  ).toBeVisible();
  expect(probes).toBe(1);
  expect(saves).toHaveLength(0);
  await page.screenshot({ path: testInfo.outputPath("model-editor.png") });
  const readsBeforeSave = catalogReads;
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page
      .getByRole("dialog", { name: "Settings", exact: true })
      .getByText("Demo model", { exact: true }),
  ).toBeVisible();
  await expect.poll(() => catalogReads).toBeGreaterThan(readsBeforeSave);
  await page.getByRole("button", { name: "Edit model", exact: true }).click();
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await page.getByLabel("Display name").fill("Updated model");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page
      .getByRole("dialog", { name: "Settings", exact: true })
      .getByText("Updated model", { exact: true }),
  ).toBeVisible();
  expect(saves[1]?.config).not.toHaveProperty("api_key");
  expect(saves[1]?.expected_revision).toBe("1");
  await page.getByRole("button", { name: "Disable", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Enable", exact: true }),
  ).toBeVisible();
  expect(saves[2]?.config.enabled).toBe(false);
});
