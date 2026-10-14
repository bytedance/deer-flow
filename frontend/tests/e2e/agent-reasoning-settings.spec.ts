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
  }, testInfo) => {
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
      if (state === "pending" || state === "loaded") {
        const path = testInfo.outputPath(`agent-settings-${state}.png`);
        await page.screenshot({ path });
        await testInfo.attach(`agent-settings-${state}`, {
          path,
          contentType: "image/png",
        });
      }
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();
      expect(requests).toHaveLength(1);
      expect(requests[0]).toMatchObject({ display_name: "Renamed reviewer" });
      expect(requests[0]).not.toHaveProperty("thinking_enabled");
      expect(requests[0]).not.toHaveProperty("reasoning_effort");
    } finally {
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
  await dialog.getByRole("combobox").first().click();
  await page.getByRole("option", { name: "Plain model", exact: true }).click();
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(saved).toMatchObject({
    model: "plain",
    thinking_enabled: null,
    reasoning_effort: null,
  });
});
