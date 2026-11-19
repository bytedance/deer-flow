import { expect, test } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

for (const width of [1280, 390]) {
  test(`agent knowledge binding persists and seeds chat at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    const agent: Record<string, unknown> & { name: string } = {
      name: "researcher",
      description: "Policy specialist",
      tool_groups: ["knowledge"],
    };
    mockLangGraphAPI(page, {
      agents: [agent],
      features: { knowledgeScopeSelectionEnabled: true },
    });
    const saves: Record<string, unknown>[] = [];
    await page.route("**/api/agents/researcher", (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        saves.push(body);
        Object.assign(agent, body);
      }
      return route.fulfill({ json: agent });
    });
    await page.route("**/api/knowledge/retrieval-catalog/datasets?*", (route) =>
      route.fulfill({
        json: {
          items: [
            { id: "policies", name: "Company policies", selectable: true },
          ],
          page: 1,
          page_size: 100,
          total: 1,
        },
      }),
    );
    await page.goto("/workspace/agents");
    await page.getByTitle("Agent settings", { exact: true }).click();
    await page.getByTestId("knowledge-scope-trigger").click();
    await page.getByLabel("Selected knowledge bases").check();
    await page.getByLabel("Company policies", { exact: true }).check();
    await page.getByRole("button", { name: "Apply", exact: true }).click();
    await expect(
      page
        .getByRole("dialog", { name: "Agent settings", exact: true })
        .getByText("Company policies", { exact: true }),
    ).toBeVisible();
    const dialog = page.getByRole("dialog", {
      name: "Agent settings",
      exact: true,
    });
    await expect(dialog).toHaveCSS("opacity", "1");
    await page.screenshot({
      path: testInfo.outputPath(`agent-knowledge-${width}.png`),
    });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect.poll(() => saves.length).toBe(1);
    expect(saves[0]).toMatchObject({
      knowledge_scope: {
        version: 1,
        mode: "selected",
        dataset_ids: ["policies"],
      },
    });
    await page.getByTitle("Agent settings", { exact: true }).click();
    await expect(
      page
        .getByRole("dialog", { name: "Agent settings", exact: true })
        .getByText("Company policies", { exact: true }),
    ).toBeVisible();
    // Saving another field must not overwrite a concurrently edited binding.
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect.poll(() => saves.length).toBe(2);
    expect(saves[1]).not.toHaveProperty("knowledge_scope");

    let submitted: Record<string, unknown> | undefined;
    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      submitted = route.request().postDataJSON() as Record<string, unknown>;
      return handleRunStream(route);
    });
    await page.goto("/workspace/agents/researcher/chats/new");
    await expect(page.getByTestId("knowledge-scope-trigger")).toHaveAttribute(
      "aria-label",
      "Knowledge · 1 base",
    );
    await page
      .getByPlaceholder(/how can i assist you/i)
      .fill("Find the leave policy");
    await page.getByRole("button", { name: "Submit" }).click();
    await expect.poll(() => submitted).toBeDefined();
    expect(submitted).toMatchObject({
      assistant_id: "researcher",
      input: {
        messages: [
          {
            additional_kwargs: {
              knowledge_scope: { mode: "selected", dataset_ids: ["policies"] },
            },
          },
        ],
      },
    });
    // Refresh rehydrates the saved agent default; an explicit per-turn opt-out wins.
    await page.goto("/workspace/agents/researcher/chats/new");
    await expect(page.getByTestId("knowledge-scope-trigger")).toHaveAttribute(
      "aria-label",
      "Knowledge · 1 base",
    );
    await page.getByTestId("knowledge-scope-trigger").click();
    await page.getByLabel("Off", { exact: true }).check();
    await page.getByRole("button", { name: "Apply", exact: true }).click();
    submitted = undefined;
    await page
      .getByPlaceholder(/how can i assist you/i)
      .fill("Do not search knowledge");
    await page.getByRole("button", { name: "Submit" }).click();
    await expect.poll(() => submitted).toBeDefined();
    expect(submitted).toMatchObject({
      input: {
        messages: [
          { additional_kwargs: { knowledge_scope: { mode: "disabled" } } },
        ],
      },
    });

    await page.goto("/workspace/agents");
    await page.getByTitle("Agent settings", { exact: true }).click();
    await page
      .getByRole("button", { name: "Use all knowledge bases", exact: true })
      .click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect.poll(() => saves.length).toBe(3);
    expect(saves[2]).toHaveProperty("knowledge_scope", null);
  });
}
