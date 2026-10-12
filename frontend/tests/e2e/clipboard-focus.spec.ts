import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test("clipboard fallback restores focus to an SVG control", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
  });
  mockLangGraphAPI(page);
  await page.goto("/workspace/chats/new");
  await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible();
  await page.evaluate(() => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("tabindex", "0");
    svg.setAttribute("data-testid", "svg-copy");
    svg.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        void navigator.clipboard.writeText("SVG copy").then(
          () => {
            svg.dataset.result = "copied";
          },
          () => {
            svg.dataset.result = "failed";
          },
        );
      }
    });
    document.body.appendChild(svg);
  });
  const svg = page.getByTestId("svg-copy");
  await svg.focus();
  await svg.press("Enter");
  await expect(svg).toHaveAttribute("data-result", "copied");
  await expect(svg).toBeFocused();
});

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
