import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const EMPTY_MEMORY = {
  version: "1.0",
  lastUpdated: "",
  user: {
    workContext: { summary: "", updatedAt: "" },
    personalContext: { summary: "", updatedAt: "" },
    topOfMind: { summary: "", updatedAt: "" },
    cognitiveStyle: { summary: "", updatedAt: "" },
  },
  history: {
    recentMonths: { summary: "", updatedAt: "" },
    earlierContext: { summary: "", updatedAt: "" },
    longTermBackground: { summary: "", updatedAt: "" },
  },
  facts: [],
};

const LEGACY_MEMORY_WITHOUT_COGNITIVE_STYLE = {
  version: "1.0",
  lastUpdated: "2026-01-01T00:00:00Z",
  user: {
    workContext: { summary: "Works on DeerFlow", updatedAt: "" },
    personalContext: { summary: "", updatedAt: "" },
    topOfMind: { summary: "Memory import compatibility", updatedAt: "" },
  },
  history: {
    recentMonths: { summary: "", updatedAt: "" },
    earlierContext: { summary: "", updatedAt: "" },
    longTermBackground: { summary: "", updatedAt: "" },
  },
  facts: [
    {
      content: "User prefers conclusions first.",
      category: "cognitive",
    },
  ],
};

async function openMemorySettings(page: Page) {
  mockLangGraphAPI(page);
  await page.route(/\/api\/memory$/, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(EMPTY_MEMORY),
      });
      return;
    }
    await route.fallback();
  });

  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();

  const settingsDialog = page.getByRole("dialog", { name: "Settings" });
  await expect(settingsDialog).toBeVisible();
  await settingsDialog.getByRole("button", { name: "Memory" }).click();
  await expect(
    settingsDialog.getByRole("button", { name: "Import memory" }),
  ).toBeVisible();
  return settingsDialog;
}

async function selectMemoryFile(
  settingsDialog: ReturnType<Page["getByRole"]>,
  fileName: string,
  payload: unknown,
) {
  await settingsDialog.locator('input[type="file"]').setInputFiles({
    name: fileName,
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(payload)),
  });
}

const invalidImports = [
  {
    name: "facts-only JSON",
    fileName: "facts-only.json",
    payload: { facts: [] },
  },
  {
    name: "missing metadata",
    fileName: "missing-metadata.json",
    payload: { user: {}, history: {}, facts: [] },
  },
  {
    name: "non-object user/history",
    fileName: "invalid-sections.json",
    payload: {
      version: "1.0",
      lastUpdated: "2026-07-17T00:00:00Z",
      user: "not-an-object",
      history: 123,
      facts: [],
    },
  },
];

test.describe("Memory settings import validation", () => {
  for (const invalidImport of invalidImports) {
    test(`does not enable confirmation for ${invalidImport.name}`, async ({
      page,
    }) => {
      const settingsDialog = await openMemorySettings(page);

      await selectMemoryFile(
        settingsDialog,
        invalidImport.fileName,
        invalidImport.payload,
      );

      await expect(
        page.getByText(
          "Failed to read the selected memory file. Please choose a valid JSON export.",
        ),
      ).toBeVisible();
      await expect(
        page.getByRole("dialog", { name: "Import memory?" }),
      ).toHaveCount(0);
    });
  }

  test("keeps confirmation available for a legacy export missing cognitiveStyle", async ({
    page,
  }) => {
    const settingsDialog = await openMemorySettings(page);

    await selectMemoryFile(
      settingsDialog,
      "legacy-without-cognitive-style.json",
      LEGACY_MEMORY_WITHOUT_COGNITIVE_STYLE,
    );

    const confirmDialog = page.getByRole("dialog", { name: "Import memory?" });
    await expect(confirmDialog).toBeVisible();
    await expect(confirmDialog).toContainText(
      "legacy-without-cognitive-style.json",
    );
    await expect(
      confirmDialog.getByRole("button", { name: "Import" }),
    ).toBeEnabled();
  });

  test("round-trips unknown fields through the import request", async ({
    page,
  }) => {
    const memoryWithExtensions = {
      ...LEGACY_MEMORY_WITHOUT_COGNITIVE_STYLE,
      revision: 4,
      display: { title: "Memory export" },
      data: { future: true },
    };
    const importedPayloads: unknown[] = [];
    await page.route(/\/api\/memory\/import$/, async (route) => {
      if (route.request().method() === "POST") {
        importedPayloads.push(route.request().postDataJSON());
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(memoryWithExtensions),
        });
        return;
      }
      await route.fallback();
    });

    const settingsDialog = await openMemorySettings(page);
    await selectMemoryFile(
      settingsDialog,
      "with-extensions.json",
      memoryWithExtensions,
    );

    const confirmDialog = page.getByRole("dialog", { name: "Import memory?" });
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole("button", { name: "Import" }).click();

    await expect.poll(() => importedPayloads.length).toBe(1);
    expect(importedPayloads[0]).toMatchObject({
      revision: 4,
      display: { title: "Memory export" },
      data: { future: true },
      user: { cognitiveStyle: { summary: "", updatedAt: "" } },
    });
  });
});
