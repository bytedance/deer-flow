import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("hides image model settings when management is disabled", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    features: { imageGenerationManagementEnabled: false },
  });
  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings", exact: true });
  await settings.getByRole("button", { name: "Models" }).click();
  await expect(settings.getByText("Image models", { exact: true })).toHaveCount(
    0,
  );
});

test("administrator selects a persistent image default in Settings", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page);
  let selected: "managed" | "sandbox_environment" | null = null;
  let revision: string | null = null;
  let savedBody: Record<string, unknown> | null = null;

  await page.route("**/api/managed-models", (route) =>
    route.fulfill({ json: { models: [] } }),
  );

  await page.route("**/api/image-generation/profiles", (route) =>
    route.fulfill({
      json: {
        profiles: [
          {
            name: "server-config",
            display_name: "Server configuration",
            source: "config",
            provider: "openai",
            model: "qwen-image-2.0",
            base_url: "https://images.example/v1",
            identity: "server-identity",
            has_api_key: true,
            enabled: false,
            selected: selected === "sandbox_environment",
            conflict: selected === null,
            verified_generation: false,
            verified_edit: false,
          },
          {
            name: "web-image",
            display_name: "qwen-image-3.0",
            source: "managed",
            provider: "openai",
            model: "qwen-image-3.0",
            base_url: "https://images.example/v1",
            identity: "web-identity",
            has_api_key: true,
            enabled: true,
            selected: selected === "managed",
            conflict: selected === null,
            revision: "web-revision",
            verified_generation: true,
            verified_edit: false,
          },
        ],
        status: {
          status: "configured_unverified",
          source: selected ?? "managed",
          provider: "openai",
          model:
            selected === "sandbox_environment"
              ? "qwen-image-2.0"
              : "qwen-image-3.0",
          has_api_key: true,
          supports_generation: false,
          supports_edit: false,
          choice_required: selected === null,
          default_revision: revision,
          default_active: selected !== null,
        },
      },
    }),
  );
  await page.route("**/api/image-generation/profiles/default", (route) => {
    savedBody = route.request().postDataJSON() as Record<string, unknown>;
    selected = savedBody.source as "managed" | "sandbox_environment";
    revision = "saved-revision";
    return route.fulfill({ json: { revision } });
  });

  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings", exact: true });
  await expect(settings).toBeVisible();
  await settings.getByRole("button", { name: "Models" }).click();
  await expect(settings).toBeVisible();
  await expect(
    settings.getByText("Image models", { exact: true }),
  ).toBeVisible();
  await settings
    .getByRole("button", { name: "Use Server configuration as default" })
    .click();
  const selectedTag = settings.getByLabel(
    "Default image model: Server configuration",
  );
  await expect(selectedTag).toBeVisible();
  expect(savedBody).toMatchObject({
    source: "sandbox_environment",
    target_identity: "server-identity",
    expected_revision: null,
  });
  await settings
    .locator("[data-radix-scroll-area-viewport]")
    .evaluate((viewport) => {
      viewport.scrollTop = viewport.scrollHeight;
    });
  await page.screenshot({
    path: testInfo.outputPath("image-default-selected.png"),
  });
});
