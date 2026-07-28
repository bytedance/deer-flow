import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, waitFor } from "@testing-library/react";

import { MarkdownContent } from "@/components/workspace/messages/markdown-content";

afterEach(cleanup);

describe("MarkdownContent streaming list transitions (DOM)", () => {
  it("reveals the same list item with marker animation when content arrives", async () => {
    const { container, rerender } = render(
      <MarkdownContent content={"1. First\n\n2."} isLoading={true} />,
    );
    const initialItems = container.querySelectorAll<HTMLLIElement>(
      '[data-streamdown="list-item"]',
    );
    const firstItem = initialItems[0]!;
    const pendingItem = initialItems[1]!;

    expect(pendingItem.hidden).toBe(true);
    expect(pendingItem.hasAttribute("data-streaming-list-item")).toBe(false);

    rerender(
      <MarkdownContent content={"1. First\n\n2. Second"} isLoading={true} />,
    );

    await waitFor(() => {
      expect(pendingItem.textContent).toContain("Second");
    });
    const revealedItems = container.querySelectorAll<HTMLLIElement>(
      '[data-streamdown="list-item"]',
    );

    expect(revealedItems[0]).toBe(firstItem);
    expect(revealedItems[1]).toBe(pendingItem);
    expect(pendingItem.hidden).toBe(false);
    expect(pendingItem.getAttribute("data-streaming-list-item")).toBe("true");
  });
});
