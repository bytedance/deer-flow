import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000004579";

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
    await expect.poll(() => code.textContent()).toContain(literal);
    await expect(page.locator(".katex")).toHaveCount(1);
    await page.screenshot({
      path: testInfo.outputPath("markdown-code-fence.png"),
    });
  });
}
