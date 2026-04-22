import { expect, test } from "@playwright/test";

import {
  handleRunStream,
  MOCK_THREAD_ID_2,
  mockLangGraphAPI,
} from "./utils/mock-api";

test.describe("Chat workspace", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("new chat page loads with input box", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
  });

  test("can type a message in the input box", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Hello, DeerFlow!");
    await expect(textarea).toHaveValue("Hello, DeerFlow!");
  });

  test("sending a message triggers API call and shows response", async ({
    page,
  }) => {
    let streamCalled = false;
    await page.route("**/runs/stream", (route) => {
      streamCalled = true;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Hello");
    await textarea.press("Enter");

    await expect.poll(() => streamCalled, { timeout: 10_000 }).toBeTruthy();

    // The AI response should appear in the chat
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("shows archived messages after summarization without showing the summary", async ({
    page,
  }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID_2,
          title: "LLM Wiki Report Outline",
          values: {
            display_messages: [
              {
                type: "human",
                id: "archived-human-1",
                content: [
                  {
                    type: "text",
                    text: "Generate a McKinsey-grade research report on LLM Wiki.",
                  },
                ],
              },
              {
                type: "ai",
                id: "archived-ai-1",
                content: "I will gather sources and build the report outline.",
              },
            ],
            messages: [
              {
                type: "human",
                id: "summary-hidden",
                content:
                  "Here is a summary of the conversation to date:\n\nCore Task...",
                additional_kwargs: { hide_from_ui: true },
              },
              {
                type: "ai",
                id: "current-ai-1",
                content: "Continuing with the final report section.",
              },
            ],
          },
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID_2}`);

    await expect(
      page.getByText("Generate a McKinsey-grade research report on LLM Wiki."),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByText("I will gather sources and build the report outline."),
    ).toBeVisible();
    await expect(
      page.getByText("Continuing with the final report section."),
    ).toBeVisible();
    await expect(
      page.getByText("Here is a summary of the conversation to date"),
    ).toHaveCount(0);
  });
});
