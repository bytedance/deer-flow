import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const agent = {
  name: "test-agent",
  model: "reasoner",
  thinking_enabled: false,
  reasoning_effort: "high",
};
const models = [
  {
    name: "reasoner",
    display_name: "Reasoner",
    supports_thinking: true,
    supports_reasoning_effort: true,
  },
  {
    name: "plain",
    display_name: "Plain model",
    supports_thinking: false,
    supports_reasoning_effort: false,
  },
];

async function mockSettingsDependencies(page: Page) {
  mockLangGraphAPI(page, { agents: [agent] });
  await page.route("**/api/subagents", (route) =>
    route.fulfill({ json: { subagents: [] } }),
  );
  await page.route("**/api/agent-tool-groups", (route) =>
    route.fulfill({ json: { tool_groups: [] } }),
  );
}

for (const state of ["pending", "failed", "loaded", "missing"] as const) {
  test(`rename preserves saved reasoning when model catalog is ${state}`, async ({
    page,
  }) => {
    await mockSettingsDependencies(page);
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let catalogResponses = 0;
    await page.route("**/api/models", async (route) => {
      if (state === "pending") await held;
      await route.fulfill(
        state === "failed"
          ? { status: 503, json: { detail: "Catalog unavailable" } }
          : {
              json: {
                models: state === "missing" ? [models[1]] : models,
                token_usage: { enabled: false },
              },
            },
      );
      catalogResponses += 1;
    });
    const requests: Record<string, unknown>[] = [];
    await page.route("**/api/agents/test-agent", (route) => {
      if (route.request().method() === "PUT") {
        const request = route.request().postDataJSON() as Record<
          string,
          unknown
        >;
        requests.push(request);
        return route.fulfill({ json: { ...agent, ...request } });
      }
      return route.fulfill({ json: agent });
    });
    try {
      await page.goto("/workspace/agents", { waitUntil: "domcontentloaded" });
      await page.getByTitle("Agent settings", { exact: true }).click();
      const dialog = page.getByRole("dialog");
      if (state === "failed" || state === "missing") {
        await expect
          .poll(() => catalogResponses)
          .toBeGreaterThanOrEqual(state === "failed" ? 2 : 1);
      }
      if (state === "loaded")
        await expect(
          dialog.getByText("Thinking mode", { exact: true }),
        ).toBeVisible();
      await dialog.getByLabel("Display name").fill("Renamed reviewer");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();
      expect(requests).toHaveLength(1);
      expect(requests[0]).toMatchObject({ display_name: "Renamed reviewer" });
      expect(requests[0]).not.toHaveProperty("thinking_enabled");
      expect(requests[0]).not.toHaveProperty("reasoning_effort");
    } finally {
      await page.unrouteAll({ behavior: "ignoreErrors" });
      release?.();
    }
  });
}

test("an explicit switch to a model without reasoning clears incompatible defaults", async ({
  page,
}) => {
  await mockSettingsDependencies(page);
  await page.route("**/api/models", (route) =>
    route.fulfill({ json: { models, token_usage: { enabled: false } } }),
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
  await expect(
    dialog.getByText("Thinking mode", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("combobox", { name: "Default model", exact: true })
    .click();
  await page.getByRole("option", { name: "Plain model", exact: true }).click();
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(saved).toMatchObject({
    model: "plain",
    thinking_enabled: null,
    reasoning_effort: null,
  });
});

const requiredModel = {
  ...models[0],
  name: "required",
  display_name: "Required model",
  reasoning: {
    thinking: "required",
    effort: { values: ["low"], default: "low", aliases: {} },
    history: null,
    source: "contract",
  },
};

test("stale reasoning values are visible and can be explicitly cleared", async ({
  page,
}) => {
  await mockSettingsDependencies(page);
  await page.route("**/api/models", (route) =>
    route.fulfill({
      json: {
        models: [{ ...requiredModel, name: "reasoner" }],
        token_usage: { enabled: false },
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
  const thinking = dialog.getByRole("combobox", {
    name: "Thinking mode",
    exact: true,
  });
  const effort = dialog.getByRole("combobox", {
    name: "Reasoning effort",
    exact: true,
  });
  await expect(thinking).toContainText("Off (not supported)");
  await expect(effort).toContainText("high (not supported)");
  await expect(dialog.getByRole("alert")).toContainText(
    "can prevent runs from starting",
  );
  await thinking.click();
  await page.getByRole("option", { name: "Inherit", exact: true }).click();
  await effort.click();
  await page.getByRole("option", { name: "Inherit", exact: true }).click();
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(saved).toMatchObject({
    thinking_enabled: null,
    reasoning_effort: null,
  });
  expect(saved).not.toHaveProperty("model");
});

for (const state of ["pending", "failed"] as const) {
  test(`global-default switch waits for a ${state} catalog and normalizes the resolved model`, async ({
    page,
  }) => {
    await mockSettingsDependencies(page);
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let ready = false;
    let responses = 0;
    await page.route("**/api/models", async (route) => {
      if (!ready && state === "pending") await held;
      if (!ready) {
        await route.fulfill({
          status: 503,
          json: { detail: "Catalog unavailable" },
        });
      } else {
        await route.fulfill({
          json: {
            models: [requiredModel, ...models],
            token_usage: { enabled: false },
          },
        });
      }
      responses += 1;
    });
    let saved: Record<string, unknown> | undefined;
    await page.route("**/api/agents/test-agent", (route) => {
      if (route.request().method() === "PUT") {
        saved = route.request().postDataJSON() as Record<string, unknown>;
        return route.fulfill({ json: { ...agent, ...saved } });
      }
      return route.fulfill({ json: agent });
    });
    try {
      await page.goto("/workspace/agents", { waitUntil: "domcontentloaded" });
      await page.getByTitle("Agent settings", { exact: true }).click();
      const dialog = page.getByRole("dialog");
      if (state === "failed")
        await expect.poll(() => responses).toBeGreaterThanOrEqual(2);
      await dialog
        .getByRole("combobox", { name: "Default model", exact: true })
        .click();
      await page
        .getByRole("option", { name: "Use global default", exact: true })
        .click();
      await expect(
        dialog.getByRole("button", { name: "Save", exact: true }),
      ).toBeDisabled();
      await expect(dialog.getByRole("status")).toContainText(
        "Load the selected model before saving",
      );
      expect(saved).toBeUndefined();
      ready = true;
      if (state === "pending") release();
      else
        await dialog
          .getByRole("button", { name: "Retry", exact: true })
          .click();
      await expect(
        dialog.getByRole("button", { name: "Save", exact: true }),
      ).toBeEnabled();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();
      expect(saved).toMatchObject({
        model: null,
        thinking_enabled: null,
        reasoning_effort: null,
      });
    } finally {
      await page.unrouteAll({ behavior: "ignoreErrors" });
      release();
    }
  });
}
