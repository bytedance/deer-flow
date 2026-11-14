import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const worker = {
  name: "researcher",
  display_name: "Researcher",
  description: "Investigate a delegated question and check the evidence.",
  system_prompt: "Check the sources and report your findings to the caller.",
  model: "inherit",
  thinking_enabled: null,
  reasoning_effort: null,
  reasoning_source: "inherit",
  tools: null,
  skills: null,
  max_turns: 50,
  timeout_seconds: 900,
  enabled: true,
  source: "managed",
  editable: true,
  conflict: false,
  config_overrides: {},
};

const models = [
  {
    name: "reasoner",
    display_name: "Reasoning model",
    reasoning: {
      thinking: "required",
      effort: {
        values: ["lite", "deep"],
        default: "lite",
        aliases: { high: "deep" },
      },
      source: "contract",
      history: null,
    },
  },
  { name: "plain", display_name: "Plain model", supports_thinking: false },
];

async function openEditor(
  page: Page,
  overrides = {},
  catalog: "loaded" | "pending" | "failed" | "missing" = "loaded",
) {
  mockLangGraphAPI(page);
  await page.route("**/api/subagents", (route) =>
    route.fulfill({ json: { subagents: [{ ...worker, ...overrides }] } }),
  );
  let release: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let catalogResponses = 0;
  await page.route("**/api/models", async (route) => {
    if (catalog === "pending") await held;
    await route.fulfill(
      catalog === "failed"
        ? { status: 503, json: { detail: "Unavailable" } }
        : {
            json: {
              models: catalog === "missing" ? [] : models,
              token_usage: { enabled: false },
            },
          },
    );
    catalogResponses += 1;
  });
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/subagents/researcher", (route) => {
    const request = route.request().postDataJSON() as Record<string, unknown>;
    requests.push(request);
    return route.fulfill({ json: { ...worker, ...overrides, ...request } });
  });
  await page.goto("/workspace/chats/new", {
    waitUntil: "domcontentloaded",
  });
  if (page.viewportSize()!.width < 768) {
    const trigger = page.getByRole("button", {
      name: "Toggle Sidebar",
      exact: true,
    });
    await expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    await trigger.click();
  }
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: /Settings and more/ })
    .click();
  await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Settings", exact: true })
    .getByRole("button", { name: "Subagents", exact: true })
    .click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Edit managed subagent" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveCSS("opacity", "1");
  await page.evaluate(() => document.fonts.ready);
  if (catalog === "failed" || catalog === "missing") {
    await expect
      .poll(() => catalogResponses)
      .toBeGreaterThanOrEqual(catalog === "failed" ? 2 : 1);
  }
  return { dialog, requests, release };
}

async function choose(page: Page, label: string, option: string) {
  await page.getByRole("combobox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("reasoning source and explicit Off are saved independently", async ({
  page,
}) => {
  const { dialog, requests } = await openEditor(page);
  await expect(
    dialog.getByRole("combobox", { name: "Reasoning defaults", exact: true }),
  ).toHaveText("Inherit from caller");
  await choose(page, "Reasoning defaults", "Use model defaults");
  await choose(page, "Thinking override", "Off");
  await choose(page, "Effort override", "high");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    reasoning_source: "model",
    thinking_enabled: false,
    reasoning_effort: "high",
  });
});

test("clearing overrides restores inheritance", async ({ page }) => {
  const { dialog, requests } = await openEditor(page, {
    thinking_enabled: false,
    reasoning_effort: "high",
    reasoning_source: "model",
  });
  await choose(page, "Reasoning defaults", "Inherit from caller");
  await choose(page, "Thinking override", "Use selected defaults");
  await choose(page, "Effort override", "Use selected defaults");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(requests[0]).toMatchObject({
    reasoning_source: "inherit",
    thinking_enabled: null,
    reasoning_effort: null,
  });
});

test("switching models uses the child capability contract", async ({
  page,
}) => {
  const { dialog, requests } = await openEditor(page, {
    thinking_enabled: false,
    reasoning_effort: "high",
  });
  await choose(page, "Model", "Reasoning model");
  await expect(
    dialog.getByRole("combobox", { name: "Thinking override", exact: true }),
  ).toHaveText("Use selected defaults");
  await expect(
    dialog.getByRole("combobox", { name: "Effort override", exact: true }),
  ).toHaveText("deep");
  await page
    .getByRole("combobox", { name: "Thinking override", exact: true })
    .click();
  await expect(
    page.getByRole("option", { name: "Off", exact: true }),
  ).toHaveCount(0);
  await page.keyboard.press("Escape");
  await choose(page, "Model", "Plain model");
  await expect(
    dialog.getByRole("combobox", { name: "Effort override", exact: true }),
  ).toHaveText("Use selected defaults");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(requests[0]).toMatchObject({
    model: "plain",
    thinking_enabled: null,
    reasoning_effort: null,
  });
});

test("explicit Off is valid for a model without thinking support", async ({
  page,
}) => {
  const { dialog, requests } = await openEditor(page, {
    model: "plain",
    thinking_enabled: false,
  });
  await expect(dialog.getByText(/This saved override conflicts/)).toHaveCount(
    0,
  );
  await choose(page, "Thinking override", "Use selected defaults");
  await choose(page, "Thinking override", "Off");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(requests[0]).toMatchObject({
    model: "plain",
    thinking_enabled: false,
  });
});

for (const catalog of ["loaded", "pending", "failed", "missing"] as const) {
  test(`editing a name preserves saved overrides when catalog is ${catalog}`, async ({
    page,
  }) => {
    const { dialog, requests, release } = await openEditor(
      page,
      {
        model: "reasoner",
        thinking_enabled: false,
        reasoning_effort: "old-provider-value",
        reasoning_source: "model",
      },
      catalog,
    );
    try {
      await dialog
        .getByLabel("Display name", { exact: true })
        .fill("Renamed researcher");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();
      expect(requests[0]).toMatchObject({
        display_name: "Renamed researcher",
        model: "reasoner",
        thinking_enabled: false,
        reasoning_effort: "old-provider-value",
        reasoning_source: "model",
      });
    } finally {
      await page.unrouteAll({ behavior: "ignoreErrors" });
      release?.();
    }
  });
}

test("editor keeps save accessible on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { dialog } = await openEditor(page);
  await expect(
    dialog.getByRole("button", { name: "Save", exact: true }),
  ).toBeInViewport();
  expect(
    await dialog.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  await choose(page, "Reasoning defaults", "Use model defaults");
  await expect(
    dialog.getByRole("button", { name: "Save", exact: true }),
  ).toBeInViewport();
});

test("subagent editor screenshot", async ({ page }) => {
  test.skip(!process.env.SUBAGENT_SCREENSHOTS_DIR, "Opt-in review artifact");
  await page.setViewportSize({ width: 1440, height: 1200 });
  const { dialog } = await openEditor(page);
  await page.screenshot({
    animations: "disabled",
    path: path.join(
      process.env.SUBAGENT_SCREENSHOTS_DIR!,
      `${process.env.SUBAGENT_SCREENSHOT_PHASE ?? "after"}-light.png`,
    ),
  });
  await page.evaluate(() => {
    document.documentElement.classList.add("dark");
    document.documentElement.classList.remove("light");
  });
  await expect(dialog).toBeVisible();
  await page.screenshot({
    animations: "disabled",
    path: path.join(
      process.env.SUBAGENT_SCREENSHOTS_DIR!,
      `${process.env.SUBAGENT_SCREENSHOT_PHASE ?? "after"}-dark.png`,
    ),
  });
});
