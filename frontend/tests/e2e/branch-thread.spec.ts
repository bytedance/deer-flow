import { expect, test } from "@playwright/test";

import {
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
  mockLangGraphAPI,
  THREAD_PINNED_METADATA_KEY,
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
    await expect(branchThreadLink).toContainText("Original chat (2)");
    await expect(branchThreadLink).not.toContainText("Branch:");
    await expect(branchThreadLink).toHaveAttribute(
      "data-branch-parent-id",
      MOCK_THREAD_ID,
    );
    await expect(branchThreadLink).toHaveAttribute("data-branch-depth", "1");
    await expect(branchThreadLink).toHaveAttribute(
      "aria-label",
      "Original chat (2), branch of Original chat",
    );
    await expect(branchThreadLink.getByTestId("thread-branch-stem")).toHaveText(
      "└─",
    );

    const recentChatHrefs = await page
      .locator(
        'a[data-sidebar="menu-button"][href^="/workspace/chats/"]:not([href="/workspace/chats/new"])',
      )
      .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
    expect(recentChatHrefs).toEqual([
      `/workspace/chats/${MOCK_THREAD_ID}`,
      `/workspace/chats/${MOCK_THREAD_ID_2}`,
    ]);
  });

  test("keeps a pinned branch top-level when its parent is unpinned", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Unpinned parent",
          updated_at: "2026-08-24T00:00:00Z",
        },
        {
          thread_id: MOCK_THREAD_ID_2,
          title: "Pinned branch (2)",
          updated_at: "2026-08-24T00:01:00Z",
          metadata: {
            deerflow_branch: true,
            branch_parent_thread_id: MOCK_THREAD_ID,
            [THREAD_PINNED_METADATA_KEY]: true,
          },
        },
      ],
    });

    await page.goto("/workspace/chats/new");

    const branchLink = page.locator(
      `a[href="/workspace/chats/${MOCK_THREAD_ID_2}"]`,
    );
    await expect(branchLink).toBeVisible();
    await expect(branchLink).not.toHaveAttribute("data-branch-depth");
    await expect(branchLink.getByTestId("thread-branch-stem")).toHaveCount(0);

    const recentChatHrefs = await page
      .locator(
        'a[data-sidebar="menu-button"][href^="/workspace/chats/"]:not([href="/workspace/chats/new"])',
      )
      .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
    expect(recentChatHrefs).toEqual([
      `/workspace/chats/${MOCK_THREAD_ID_2}`,
      `/workspace/chats/${MOCK_THREAD_ID}`,
    ]);
  });
});
