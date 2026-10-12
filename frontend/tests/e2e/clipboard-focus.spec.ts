import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

for (const outcome of ["success", "false", "throw", "handoff"] as const) {
  test(`clipboard fallback preserves keyboard focus: ${outcome}`, async ({
    page,
  }) => {
    await page.addInitScript((outcome) => {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: undefined,
      });
      if (outcome === "false") document.execCommand = () => false;
      if (outcome === "throw") {
        document.execCommand = () => {
          throw new Error("Copy failed");
        };
      }
      if (outcome === "handoff") {
        document.addEventListener("copy", () => {
          document
            .querySelector<HTMLTextAreaElement>("textarea[placeholder]")
            ?.focus();
        });
      }
    }, outcome);
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Copy focus",
          messages: [
            { type: "human", id: "human-1", content: "Copy this question" },
            { type: "ai", id: "ai-1", content: "A completed answer" },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const copy = page.locator(".is-user").getByRole("button").first();
    await copy.focus();
    await expect(copy).toBeFocused();
    await copy.press("Enter");
    if (outcome === "success" || outcome === "handoff") {
      await expect(copy).toHaveAttribute("aria-label", "Copied to clipboard");
    } else {
      await expect(
        page.getByText("Failed to copy to clipboard", { exact: true }),
      ).toBeVisible();
    }
    await expect(page.locator("textarea[readonly]")).toHaveCount(0);
    if (outcome === "handoff") {
      await expect(
        page.getByPlaceholder(/how can i assist you/i),
      ).toBeFocused();
    } else {
      await expect(copy).toBeFocused();
    }
  });
}
