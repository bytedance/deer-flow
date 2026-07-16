import { expect, test } from "@playwright/test";

import {
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
  mockLangGraphAPI,
} from "./utils/mock-api";

test.describe("Branch from turn", () => {
  test("creates a new chat branch from a completed assistant turn", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Original chat",
          messages: [
            {
              type: "human",
              id: "human-1",
              content: [{ type: "text", text: "First question" }],
            },
            {
              type: "ai",
              id: "ai-1",
              content: "First answer",
            },
            {
              type: "human",
              id: "human-2",
              content: [{ type: "text", text: "Second question" }],
            },
            {
              type: "ai",
              id: "ai-2",
              content: "Intermediate answer",
            },
            {
              type: "ai",
              id: "ai-3",
              content: "",
              tool_calls: [
                {
                  id: "tool-call-1",
                  name: "write_todos",
                  args: { todos: [] },
                },
              ],
            },
            {
              type: "tool",
              id: "tool-1",
              name: "write_todos",
              tool_call_id: "tool-call-1",
              content: "Todos updated",
            },
            {
              type: "ai",
              id: "ai-4",
              content: "Final answer",
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    const historicalTurn = page
      .locator("[data-assistant-turn]")
      .filter({ hasText: "First answer" });
    const intermediateTurn = page
      .locator("[data-assistant-turn]")
      .filter({ hasText: "Intermediate answer" });
    const targetTurn = page
      .locator("[data-assistant-turn]")
      .filter({ hasText: "Final answer" });

    await expect(historicalTurn).toBeVisible();
    await historicalTurn.hover();
    await expect(
      historicalTurn.getByRole("button", { name: /branch conversation/i }),
    ).toBeVisible();

    await expect(intermediateTurn).toBeVisible();
    await intermediateTurn.hover();
    await expect(
      intermediateTurn.getByRole("button", { name: /branch conversation/i }),
    ).toHaveCount(0);

    await expect(targetTurn).toBeVisible();

    await targetTurn.hover();
    await targetTurn
      .getByRole("button", { name: /branch conversation/i })
      .click();

    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID_2}$`),
    );
    await expect(page.getByText("Final answer")).toBeVisible();
    const branchThreadLink = page.locator(
      `a[href="/workspace/chats/${MOCK_THREAD_ID_2}"]`,
    );
    await expect(branchThreadLink).toContainText("Original chat");
    await expect(branchThreadLink).not.toContainText("Branch:");
  });
});
