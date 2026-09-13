import { expect, test } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

test.describe("custom-agent knowledge scope", () => {
  test("selects one file and sends one immutable scope snapshot", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: [
        {
          name: "researcher",
          description: "Research agent",
          tool_groups: ["knowledge"],
        },
      ],
      features: { knowledgeScopeSelectionEnabled: true },
    });
    await page.route("**/api/knowledge/retrieval-catalog/datasets?*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{ id: "dataset-1", name: "Policies", selectable: true }],
          page: 1,
          page_size: 100,
          total: 1,
        }),
      }),
    );
    await page.route(
      "**/api/knowledge/retrieval-catalog/datasets/dataset-1/documents?*",
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              { id: "doc-1", name: "Leave.pdf", selectable: true },
              { id: "doc-2", name: "Parsing.pdf", selectable: false },
            ],
            page: 1,
            page_size: 100,
            total: 2,
          }),
        }),
    );
    let streamBody: Record<string, unknown> | undefined;
    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      streamBody = route.request().postDataJSON() as Record<string, unknown>;
      return handleRunStream(route);
    });

    await page.goto("/workspace/agents/researcher/chats/new");
    await expect(page.getByRole("link", { name: "Knowledge" })).toHaveCount(0);
    const trigger = page.getByTestId("knowledge-scope-trigger");
    await expect(trigger).toHaveText("");
    await expect(trigger).toHaveAttribute("aria-pressed", "true");
    await expect(trigger).toHaveClass(/bg-primary\/10/);

    await trigger.click();
    await page.getByLabel("Off").check();
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(trigger).toHaveAttribute("aria-pressed", "false");
    await expect(trigger).toHaveAttribute("aria-label", "Knowledge · Off");
    await expect(trigger).not.toHaveClass(/bg-primary\/10/);

    await trigger.click();
    await page.getByLabel("Selected knowledge bases").check();
    await page.getByLabel("Policies").check();
    await page.getByRole("button", { name: "Files" }).click();
    await page.getByLabel("Selected files").check();
    await page.getByLabel("Leave.pdf").check();
    await expect(page.getByLabel("Parsing.pdf")).toBeDisabled();
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(trigger).toHaveAttribute("aria-pressed", "true");
    await expect(trigger).toHaveClass(/bg-primary\/10/);

    await page
      .getByPlaceholder(/how can i assist you/i)
      .fill("Find the policy");
    await page.getByRole("button", { name: "Submit" }).click();
    await expect.poll(() => streamBody).toBeDefined();

    expect(streamBody).toMatchObject({
      assistant_id: "researcher",
      input: {
        messages: [
          {
            type: "human",
            additional_kwargs: {
              knowledge_scope: {
                version: 1,
                mode: "selected",
                dataset_ids: ["dataset-1"],
                document_filters: [
                  { dataset_id: "dataset-1", document_ids: ["doc-1"] },
                ],
                display: {
                  datasets: [
                    {
                      id: "dataset-1",
                      name: "Policies",
                      documents: [{ id: "doc-1", name: "Leave.pdf" }],
                    },
                  ],
                },
              },
            },
          },
        ],
      },
    });
  });

  test("ordinary chat has no selector and never loads the retrieval catalog", async ({
    page,
  }) => {
    let catalogRequests = 0;
    mockLangGraphAPI(page, {
      features: { knowledgeScopeSelectionEnabled: true },
    });
    await page.route("**/api/knowledge/retrieval-catalog/**", (route) => {
      catalogRequests += 1;
      return route.abort();
    });

    await page.goto("/workspace/chats/new");

    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible();
    await expect(page.getByTestId("knowledge-scope-trigger")).toHaveCount(0);
    expect(catalogRequests).toBe(0);
  });
});
