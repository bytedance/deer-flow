import { expect, test, type Page } from "@playwright/test";

import { type Model } from "@/core/models/types";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const MODELS: Model[] = [
  {
    id: "alpha-api",
    name: "alpha-api",
    model: "alpha-api",
    display_name: "Alpha",
    supports_thinking: false,
    supports_reasoning_effort: false,
  },
  {
    id: "beta-api",
    name: "beta-api",
    model: "beta-api",
    display_name: "Shared",
    supports_thinking: true,
    supports_reasoning_effort: true,
  },
  {
    id: "beta-duplicate",
    name: "beta-duplicate",
    model: "beta-duplicate",
    display_name: "Shared",
    supports_thinking: true,
    supports_reasoning_effort: true,
  },
  {
    id: "very-long-model-name",
    name: "very-long-model-name",
    model: "provider/very-long-model-name-that-must-stay-inside-the-dialog",
    display_name:
      "A very long model display name that must truncate on narrow screens",
    supports_thinking: true,
    supports_reasoning_effort: true,
  },
];

type InstallOptions = Parameters<typeof mockLangGraphAPI>[1];

async function installPageMocks(
  page: Page,
  options?: InstallOptions,
): Promise<{ setModels: (models: Model[]) => void }> {
  mockLangGraphAPI(page, options);
  let models = MODELS;

  // Register this after the shared mock so every page explicitly supplies the
  // model catalog exercised by this spec.
  await page.route("**/api/models", (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        models,
        token_usage: { enabled: false },
      }),
    });
  });

  return {
    setModels(nextModels) {
      models = nextModels;
    },
  };
}

function picker(page: Page) {
  return page.getByRole("dialog", { name: "Choose a model" });
}

function favoriteButton(page: Page, modelName: string) {
  const model = MODELS.find((candidate) => candidate.name === modelName);
  if (!model) {
    throw new Error(`Unknown model fixture: ${modelName}`);
  }
  return picker(page).getByRole("button", {
    name: `Favorite ${model.display_name} (${model.name})`,
  });
}

function favoriteGroup(page: Page) {
  return picker(page).getByRole("group", { name: "Favorites" });
}

function modelButton(page: Page, modelName: string) {
  const model = MODELS.find((candidate) => candidate.name === modelName);
  if (!model) {
    throw new Error(`Unknown model fixture: ${modelName}`);
  }
  return picker(page).getByRole("button", {
    name: `${model.display_name} (${model.name})`,
    exact: true,
  });
}

async function openMainModelPicker(page: Page, name = "Alpha") {
  const trigger = page.getByRole("button", { name, exact: true }).first();
  await expect(trigger).toBeVisible();
  await trigger.click();
  await expect(picker(page)).toBeVisible();
  return trigger;
}

async function selectAssistantText(page: Page, text: string) {
  await page.evaluate((targetText) => {
    const root = document.querySelector('[data-testid="main-message-list"]');
    if (!root) {
      throw new Error("Main message list was not found");
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const value = node.textContent ?? "";
      const start = value.indexOf(targetText);
      if (start >= 0) {
        const range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, start + targetText.length);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
        node.parentElement?.dispatchEvent(
          new MouseEvent("mouseup", { bubbles: true }),
        );
        return;
      }
      node = walker.nextNode();
    }
    throw new Error(`Unable to find assistant text: ${targetText}`);
  }, text);
  await expect(
    page.getByRole("button", { name: "Ask in side chat" }),
  ).toBeVisible();
}

test("favorites a model without selecting it and persists the choice after refresh", async ({
  page,
}) => {
  await installPageMocks(page);
  const runRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/runs/stream")) {
      runRequests.push(request.url());
    }
  });

  await page.goto("/workspace/chats/new");
  const alphaTrigger = await openMainModelPicker(page);

  await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
  const pickerBox = await picker(page).boundingBox();
  const triggerBox = await alphaTrigger.boundingBox();
  expect(pickerBox).not.toBeNull();
  expect(triggerBox).not.toBeNull();
  const pickerSide = await picker(page).getAttribute("data-side");
  expect(["top", "bottom"]).toContain(pickerSide);
  const anchorGap =
    pickerSide === "top"
      ? triggerBox!.y - (pickerBox!.y + pickerBox!.height)
      : pickerBox!.y - (triggerBox!.y + triggerBox!.height);
  expect(anchorGap).toBeGreaterThanOrEqual(0);
  expect(anchorGap).toBeLessThanOrEqual(12);
  expect(pickerBox!.x).toBeGreaterThanOrEqual(0);
  expect(pickerBox!.x + pickerBox!.width).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  );

  const betaFavorite = favoriteButton(page, "beta-api");
  await betaFavorite.click();
  await expect(betaFavorite).toHaveAttribute("aria-pressed", "true");
  await expect(alphaTrigger).toContainText("Alpha");
  expect(runRequests).toEqual([]);

  const favorites = favoriteGroup(page);
  await expect(favorites).toBeVisible();
  await expect(modelButton(page, "beta-api")).toBeVisible();
  await modelButton(page, "beta-api").click();

  await expect(picker(page)).toBeHidden();
  const sharedTrigger = page.getByRole("button", {
    name: "Shared",
    exact: true,
  });
  await expect(sharedTrigger).toBeVisible();
  expect(runRequests).toEqual([]);

  await page.reload();
  await expect(sharedTrigger).toBeVisible();
  await sharedTrigger.click();
  await expect(modelButton(page, "beta-api")).toBeVisible();
});

test("synchronizes favorite additions and removals across real tabs", async ({
  context,
  page,
}) => {
  await installPageMocks(page);
  await page.goto("/workspace/chats/new");
  await openMainModelPicker(page);

  const secondPage = await context.newPage();
  await installPageMocks(secondPage);
  await secondPage.goto("/workspace/chats/new");
  await openMainModelPicker(secondPage);

  const firstTabFavorite = favoriteButton(page, "beta-api");
  const secondTabFavorite = favoriteButton(secondPage, "beta-api");
  await expect(firstTabFavorite).toHaveAttribute("aria-pressed", "false");
  await expect(secondTabFavorite).toHaveAttribute("aria-pressed", "false");

  await firstTabFavorite.click();
  await expect(firstTabFavorite).toHaveAttribute("aria-pressed", "true");
  await expect(secondTabFavorite).toHaveAttribute("aria-pressed", "true");

  await secondTabFavorite.click();
  await expect(secondTabFavorite).toHaveAttribute("aria-pressed", "false");
  await expect(firstTabFavorite).toHaveAttribute("aria-pressed", "false");
});

test("shows main-chat favorites in the side chat without changing its current model", async ({
  page,
}) => {
  const assistantText = "Use this answer for a focused follow-up.";
  await installPageMocks(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Favorites side chat",
        messages: [
          { type: "human", id: "favorites-human", content: "Help me." },
          { type: "ai", id: "favorites-ai", content: assistantText },
        ],
      },
    ],
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await expect(page.getByText(assistantText)).toBeVisible();
  await openMainModelPicker(page);
  await favoriteButton(page, "beta-api").click();
  await page.keyboard.press("Escape");

  await selectAssistantText(page, assistantText);
  await page.getByRole("button", { name: "Ask in side chat" }).click();
  await expect(
    page.getByRole("heading", { name: "Ask a follow-up" }),
  ).toBeVisible();

  const sidecarForm = page.locator("form").filter({
    has: page.getByPlaceholder(/deeper follow-up/i),
  });
  const sidecarTrigger = sidecarForm.getByRole("button", {
    name: "Alpha",
    exact: true,
  });
  await expect(sidecarTrigger).toBeVisible();
  await sidecarTrigger.click();
  await expect(modelButton(page, "beta-api")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(picker(page)).toBeHidden();
  await expect(sidecarTrigger).toBeFocused();
  await expect(sidecarTrigger).toHaveAccessibleName("Alpha");
});

test("restores a temporarily unavailable favorite and keeps the narrow picker usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 720 });
  const modelAPI = await installPageMocks(page);
  await page.goto("/workspace/chats/new");
  const trigger = await openMainModelPicker(page);

  const longNameFavorite = favoriteButton(page, "very-long-model-name");
  await expect(longNameFavorite).toBeVisible();
  const narrowMetrics = await picker(page).evaluate((dialog) => {
    const dialogBox = dialog.getBoundingClientRect();
    const longRow = dialog
      .querySelector(
        'button[aria-label="Favorite A very long model display name that must truncate on narrow screens (very-long-model-name)"]',
      )
      ?.closest("li")
      ?.getBoundingClientRect();
    return {
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      dialogLeft: dialogBox.left,
      dialogRight: dialogBox.right,
      longRowRight: longRow?.right ?? Number.POSITIVE_INFINITY,
    };
  });
  expect(narrowMetrics.documentWidth).toBeLessThanOrEqual(
    narrowMetrics.viewportWidth,
  );
  expect(narrowMetrics.dialogLeft).toBeGreaterThanOrEqual(0);
  expect(narrowMetrics.dialogRight).toBeLessThanOrEqual(
    narrowMetrics.viewportWidth,
  );
  expect(narrowMetrics.longRowRight).toBeLessThanOrEqual(
    narrowMetrics.dialogRight,
  );

  await longNameFavorite.click();
  await expect(longNameFavorite).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  await expect(picker(page)).toBeHidden();
  await expect(trigger).toBeFocused();

  modelAPI.setModels(
    MODELS.filter((model) => model.name !== "very-long-model-name"),
  );
  await page.reload();
  await openMainModelPicker(page);
  await expect(
    picker(page).getByText("very-long-model-name", { exact: true }),
  ).toHaveCount(0);
  await page.keyboard.press("Escape");

  modelAPI.setModels(MODELS);
  await page.reload();
  await openMainModelPicker(page);
  await expect(modelButton(page, "very-long-model-name")).toBeVisible();
});
