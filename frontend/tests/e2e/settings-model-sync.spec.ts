import { expect, test } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
} from "./utils/mock-api";

for (const agent of [false, true]) {
  for (const field of ["effort", "mode"] as const) {
    const removeModel = !agent && field === "effort";
    const name = removeModel
      ? "catalog removal drops the old chat effort after another chat selects Medium"
      : `${agent ? "agent" : "normal"} thread ${field} selection preserves the account model`;
    test(name, async ({ page }) => {
      mockLangGraphAPI(page, {
        agents: [
          {
            name: "researcher",
            description: "Research agent",
            reasoning_effort: "low",
          },
        ],
        threads: [MOCK_THREAD_ID, MOCK_THREAD_ID_2].map((thread_id) => ({
          thread_id,
          agent_name: agent ? "researcher" : undefined,
        })),
      });
      await page.addInitScript(
        ({ threadId }) => {
          const key = `deerflow.thread-model.${threadId}`;
          if (localStorage.getItem(key) === null)
            localStorage.setItem(key, "thread-model");
        },
        { threadId: MOCK_THREAD_ID },
      );
      let threadModelAvailable = true;
      await page.route("**/api/models", (route) =>
        route.fulfill({
          json: {
            models: [
              {
                name: "account-model",
                display_name: "Account Model",
                supports_thinking: true,
                supports_reasoning_effort: true,
              },
              {
                name: "thread-model",
                display_name: "Thread Model",
                supports_thinking: true,
                supports_reasoning_effort: true,
                reasoning: {
                  thinking: "optional",
                  source: "contract",
                  history: null,
                  effort: {
                    values: ["low", "medium", "high", "max"],
                    default: "medium",
                    aliases: {},
                  },
                },
              },
            ].filter(
              (model) => threadModelAvailable || model.name === "account-model",
            ),
          },
        }),
      );
      await page.route("**/api/v1/auth/me", (route) =>
        route.fulfill({
          json: {
            id: "00000000-0000-0000-0000-000000000028",
            email: "thread@example.com",
            system_role: "admin",
            needs_setup: false,
          },
        }),
      );
      const patches: unknown[] = [];
      let reads = 0;
      let server = {
        model_name: "account-model",
        mode: "pro",
        reasoning_effort: "medium",
        notification_enabled: true,
        // The account already has the UI language, so only the edits below are sent.
        locale: "en-US",
      };
      await page.route("**/api/v1/auth/preferences", async (route) => {
        if (route.request().method() === "PATCH") {
          const patch = route.request().postDataJSON() as Partial<
            typeof server
          >;
          patches.push(patch);
          server = { ...server, ...patch };
          await route.fulfill({ status: 204 });
        } else {
          reads++;
          await route.fulfill({ json: server });
        }
      });
      const openChat = async (id: string) => {
        const previousReads = reads;
        await page.goto(
          `/workspace/${agent ? "agents/researcher/chats" : "chats"}/${id}`,
        );
        // Activate the mocked account and wait for its current preferences.
        await page
          .locator("[data-sidebar='sidebar']")
          .getByRole("button", { name: /Settings and more/ })
          .click();
        await page.keyboard.press("Escape");
        await page.evaluate(() =>
          document.dispatchEvent(new Event("visibilitychange")),
        );
        await expect.poll(() => reads).toBeGreaterThan(previousReads);
      };
      const chooseEffort = async (label: RegExp) => {
        await page.getByRole("button", { name: /^Reasoning Effort:/ }).click();
        await page.getByRole("menuitem").filter({ hasText: label }).click();
        await page.keyboard.press("Escape");
      };
      await openChat(MOCK_THREAD_ID);
      await expect(
        page.getByRole("button", { name: "Thread Model", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: agent ? "Reasoning Effort: Low" : "Reasoning Effort: Medium",
          exact: true,
        }),
      ).toBeVisible();
      if (field === "effort") {
        await chooseEffort(removeModel ? /^Max/ : /^High/);
      } else {
        await page.getByRole("button", { name: "Pro", exact: true }).click();
        await page
          .getByRole("menuitem")
          .filter({ hasText: /^Ultra/ })
          .click();
      }
      await expect
        .poll(() => patches)
        .toEqual([
          field === "effort"
            ? { reasoning_effort: removeModel ? "max" : "high" }
            : { mode: "ultra", reasoning_effort: "high" },
        ]);
      expect(server.model_name).toBe("account-model");
      await page.keyboard.press("Escape");
      await expect(
        page.getByRole("button", { name: "Thread Model", exact: true }),
      ).toBeVisible();
      if (agent || removeModel) {
        if (field === "mode") {
          // The account saved high for Ultra, but the agent's own default is low.
          await chooseEffort(/^High/);
        }
        if (field === "mode" || removeModel) {
          await openChat(MOCK_THREAD_ID_2);
          await chooseEffort(/^Medium/);
          await expect.poll(() => server.reasoning_effort).toBe("medium");
          await openChat(MOCK_THREAD_ID);
        }
        if (removeModel) {
          await expect(
            page.getByRole("button", { name: "Reasoning Effort: Max" }),
          ).toBeVisible();
          threadModelAvailable = false;
          await openChat(MOCK_THREAD_ID);
          await expect(
            page.getByRole("button", { name: "Account Model", exact: true }),
          ).toBeVisible();
        }
        await expect(
          page.getByRole("button", {
            name: removeModel
              ? "Reasoning Effort: Medium"
              : "Reasoning Effort: High",
          }),
        ).toBeVisible();
        await page.route("**/api/langgraph/threads/*/runs/stream", (route) =>
          handleRunStream(route),
        );
        const submitted = page.waitForRequest(
          (req) =>
            req.method() === "POST" && req.url().endsWith("/runs/stream"),
        );
        await page
          .getByPlaceholder(/how can i assist you/i)
          .fill("Check this task");
        await page.getByRole("button", { name: "Send", exact: true }).click();
        expect((await submitted).postDataJSON().context).toMatchObject({
          model_name: removeModel ? "account-model" : "thread-model",
          reasoning_effort: removeModel ? "medium" : "high",
          mode_default_fields: removeModel
            ? ["thinking_enabled", "reasoning_effort"]
            : ["thinking_enabled"],
          subagent_enabled: field === "mode",
        });
      }
    });
  }
}

test("custom agent automatic default does not become an account preference", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    agents: [{ name: "researcher", description: "Research agent" }],
  });
  const patches: unknown[] = [];
  let reads = 0;
  let allowModels!: () => void;
  const modelsReady = new Promise<void>((resolve) => {
    allowModels = resolve;
  });
  await page.route("**/api/agents/researcher", (route) =>
    route.fulfill({
      json: {
        name: "researcher",
        description: "Research agent",
        model: "agent-model",
        system_prompt: "Research",
        tools: [],
        skills: [],
      },
    }),
  );
  await page.route("**/api/models", async (route) => {
    // Do not let the auth-disabled fixture select a model before the account
    // is activated. The real agent page must then choose its configured model.
    await modelsReady;
    await route.fulfill({
      json: {
        models: [
          {
            name: "first-model",
            display_name: "First Model",
            supports_thinking: true,
          },
          {
            name: "agent-model",
            display_name: "Agent Model",
            supports_thinking: true,
          },
        ],
      },
    });
  });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "00000000-0000-0000-0000-000000000027",
        email: "agent@example.com",
        system_role: "admin",
        needs_setup: false,
      },
    }),
  );
  await page.route("**/api/v1/auth/preferences", async (route) => {
    if (route.request().method() === "PATCH") {
      patches.push(route.request().postDataJSON());
      await route.fulfill({ status: 204 });
    } else {
      reads++;
      await route.fulfill({
        json: {
          model_name: null,
          mode: null,
          reasoning_effort: null,
          notification_enabled: true,
          locale: "en-US",
        },
      });
    }
  });
  await page.goto("/workspace/agents/researcher/chats/new");
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: /Settings and more/ })
    .click();
  await page.keyboard.press("Escape");
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect.poll(() => reads).toBe(1);
  allowModels();
  await expect(
    page.getByRole("button", { name: "Agent Model", exact: true }),
  ).toBeVisible();
  // Flush the local outbox cycle through a completed server read, so this also
  // catches a PATCH that would otherwise arrive just after the UI assertion.
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect.poll(() => reads).toBe(2);
  expect(patches).toEqual([]);
  // Explicit model selections on this same page must still be synchronized.
  await page.getByRole("button", { name: "Agent Model", exact: true }).click();
  await page
    .getByRole("button", { name: "First Model (first-model)", exact: true })
    .click();
  await expect.poll(() => patches).toEqual([{ model_name: "first-model" }]);
});

test("automatic model fallback cannot overwrite a slowly loaded account preference", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const patches: unknown[] = [];
  let requested = false;
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/models", (route) =>
    route.fulfill({
      json: {
        models: [
          { name: "model-a", display_name: "Model A", supports_thinking: true },
          { name: "model-b", display_name: "Model B", supports_thinking: true },
        ],
      },
    }),
  );
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "00000000-0000-0000-0000-000000000026",
        email: "model@example.com",
        system_role: "admin",
        needs_setup: false,
      },
    }),
  );
  await page.route("**/api/v1/auth/preferences", async (route) => {
    if (route.request().method() === "PATCH") {
      patches.push(route.request().postDataJSON());
      await route.fulfill({ status: 204 });
      return;
    }
    requested = true;
    await delayed;
    await route.fulfill({
      json: {
        model_name: "model-b",
        mode: "pro",
        reasoning_effort: "high",
        notification_enabled: true,
        locale: "en-US",
      },
    });
  });
  await page.goto("/workspace/chats/new");
  // Wait for actual hydration before refreshing the auth-disabled fixture's
  // AuthProvider into a session account with a deliberately slow preference GET.
  await page
    .locator("[data-sidebar='sidebar']")
    .getByRole("button", { name: /Settings and more/ })
    .click();
  await page.keyboard.press("Escape");
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect.poll(() => requested).toBe(true);
  await expect(
    page.getByRole("button", { name: "Model A", exact: true }),
  ).toBeVisible();
  release();
  await expect(
    page.getByRole("button", { name: "Model B", exact: true }),
  ).toBeVisible();
  expect(patches).toEqual([]);
});
