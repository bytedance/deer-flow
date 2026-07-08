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
              content: "Second answer",
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    const targetTurn = page
      .locator("[data-assistant-turn]")
      .filter({ hasText: "Second answer" });
    await expect(targetTurn).toBeVisible();

    await targetTurn.hover();
    await targetTurn
      .getByRole("button", { name: /branch conversation/i })
      .click();

    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID_2}$`),
    );
    await expect(page.getByText("Second answer")).toBeVisible();
    const branchThreadLink = page.locator(
      `a[href="/workspace/chats/${MOCK_THREAD_ID_2}"]`,
    );
    await expect(branchThreadLink).toContainText("Original chat");
    await expect(branchThreadLink).not.toContainText("Branch:");
  });
});
