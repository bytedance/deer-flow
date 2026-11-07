import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000004579";

test("renders math after line-start multi-backtick inline code", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Inline code followed by math",
        messages: [
          { type: "human", id: "inline-human", content: "Show code and math." },
          {
            type: "ai",
            id: "inline-ai",
            content: "```one```\n\n```two```\n\n\\(x\\)",
          },
        ],
      },
    ],
  });

  await page.goto(`/workspace/chats/${THREAD_ID}`);
  await expect(page.locator("code").filter({ hasText: /^one$/ })).toBeVisible();
  await expect(page.locator("code").filter({ hasText: /^two$/ })).toBeVisible();
  await expect(page.locator(".katex")).toHaveCount(1);
  await expect(page.locator("pre")).toHaveCount(0);
});

for (const fence of ["````", "~~~~"]) {
  test(`preserves Markdown examples inside ${fence} code fences`, async ({
    page,
  }, testInfo) => {
    const literal = [
      "```tex",
      "\\(literal\\)",
      "$$",
      "a",
      "+ b",
      "$$",
      ">".repeat(150) + "literal quote",
      " ".repeat(250) + "- literal indent",
      "```",
    ].join("\n");

    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Markdown code examples",
          messages: [
            {
              type: "human",
              id: "fence-human",
              content: "Show a Markdown example.",
            },
            {
              type: "ai",
              id: "fence-ai",
              content: `Example:\n\n${fence}text\n${literal}\n${fence}\n\nOutside \\(x\\).`,
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${THREAD_ID}`);
    const code = page.locator("pre code").filter({ hasText: "literal quote" });
    await expect(code).toBeVisible();
    await expect.poll(() => code.innerText()).toContain(literal);
    await expect(page.locator(".katex")).toHaveCount(1);
    await page.screenshot({
      path: testInfo.outputPath("markdown-code-fence.png"),
    });
  });
}
