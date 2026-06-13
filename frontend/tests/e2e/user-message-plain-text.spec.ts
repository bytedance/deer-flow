import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const C_SOURCE = `#include <stdio.h>
#include <signal.h>

static volatile int connected = 0;

static void daemon_handle_signal(int sig) {
    if (sig == SIGTERM) {
        connected = 0;

        printf("daemon stop requested\\n");
        return;
    }

    printf("ignored signal %d\\n", sig);
}`;

function threadWithMessages(
  humanText: string,
  aiText = "ack",
): Parameters<typeof mockLangGraphAPI>[1] {
  return {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Plain text rendering",
        updated_at: "2025-06-01T12:00:00Z",
        messages: [
          {
            type: "human",
            id: "msg-human-plain-text",
            content: [{ type: "text", text: humanText }],
          },
          {
            type: "ai",
            id: "msg-ai-plain-text",
            content: aiText,
          },
        ],
      },
    ],
  };
}

function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => {
    errors.push(`${error.name}: ${error.message}`);
  });
  return errors;
}

test.describe("User message plain-text rendering", () => {
  test("pasted source code renders verbatim as one block", async ({ page }) => {
    mockLangGraphAPI(page, threadWithMessages(C_SOURCE));

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("ack")).toBeVisible({ timeout: 15_000 });

    // The pasted file must not be split into Markdown code-block widgets.
    await expect(
      page.locator('[data-code-block-container="true"]'),
    ).toHaveCount(0);

    // Indentation and line structure must be preserved verbatim.
    const bubble = page.locator(".is-user");
    const text = await bubble.innerText();
    expect(text).toContain("#include <stdio.h>");
    expect(text).toContain("    if (sig == SIGTERM) {");
    expect(text).toContain('        printf("daemon stop requested\\n");');
  });

  test("dollar signs are not parsed as math", async ({ page }) => {
    const message = "this costs $5 and $10 in total";
    mockLangGraphAPI(page, threadWithMessages(message));

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("ack")).toBeVisible({ timeout: 15_000 });

    await expect(page.locator(".is-user")).toContainText(message);
    await expect(page.locator(".is-user .katex")).toHaveCount(0);
  });

  test("deeply nested blockquote markers in a user message do not crash the page", async ({
    page,
  }) => {
    const pageErrors = collectPageErrors(page);
    mockLangGraphAPI(page, threadWithMessages("> ".repeat(3000) + "hi"));

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("ack")).toBeVisible({ timeout: 15_000 });

    expect(pageErrors).toEqual([]);
    await expect(page.locator(".is-user")).toContainText("> > >");
  });

  test("deeply nested blockquote markers in an AI message do not crash the page", async ({
    page,
  }) => {
    const pageErrors = collectPageErrors(page);
    mockLangGraphAPI(
      page,
      threadWithMessages("hello", "> ".repeat(3000) + "deep"),
    );

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("hello")).toBeVisible({ timeout: 15_000 });

    expect(pageErrors).toEqual([]);
    // The capped blockquote chain still renders (100 levels of indentation can
    // squeeze the innermost element to zero width, so assert presence, not
    // visibility).
    await expect(page.getByText("deep")).toBeAttached();
  });

  test("list-prefixed deep nesting in an AI message falls back to plain text instead of crashing", async ({
    page,
  }) => {
    // marked's list and blockquote tokenizers are mutually recursive, so a
    // list marker in front of the quote chain bypasses the nesting cap; the
    // render error boundary must absorb it.
    const pageErrors = collectPageErrors(page);
    mockLangGraphAPI(
      page,
      threadWithMessages("hello", "- " + "> ".repeat(3000) + "deep-list"),
    );

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("hello")).toBeVisible({ timeout: 15_000 });

    expect(pageErrors).toEqual([]);
    await expect(page.getByText("deep-list")).toBeAttached();
  });
});
