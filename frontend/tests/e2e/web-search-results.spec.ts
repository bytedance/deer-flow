import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const shape of ["array", "webz", "webz-malformed"] as const) {
  test(`search source links from ${shape} results survive reload`, async ({
    page,
  }) => {
    const threadId = "00000000-0000-0000-0000-000000005880";
    const results: unknown[] = [
      {
        title: "Renewable energy news",
        url: "https://example.com/news",
        content: "Matching passage",
        published_at: "2026-09-20T12:00:00Z",
        source: { domain: "example.com", language: "english", country: "US" },
      },
    ];
    if (shape === "webz-malformed") {
      results.unshift(null, {
        title: { text: "Invalid title" },
        url: "https://example.com/invalid",
      });
      results.push({ title: "Invalid URL", url: 42 });
    }
    const payload =
      shape === "array"
        ? results
        : {
            query: "renewable energy",
            returned_results: results.length,
            results,
          };
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: threadId,
          title: "News research",
          messages: [
            { type: "human", id: "human", content: "Find recent energy news" },
            {
              type: "ai",
              id: "ai-search",
              content: "",
              tool_calls: [
                {
                  id: "search-5880",
                  name: "web_search",
                  args: { query: "renewable energy" },
                },
              ],
            },
            {
              type: "tool",
              id: "search-result",
              tool_call_id: "search-5880",
              name: "web_search",
              content: JSON.stringify(payload),
            },
            {
              type: "ai",
              id: "answer",
              content: "The news search is complete.",
            },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${threadId}`);
    const link = page.getByRole("link", {
      name: "Renewable energy news",
      exact: true,
    });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "https://example.com/news");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await page.reload();
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "https://example.com/news");
  });
}
