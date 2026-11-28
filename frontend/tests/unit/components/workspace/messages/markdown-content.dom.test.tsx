import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import { MarkdownContent } from "@/components/workspace/messages/markdown-content";

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("MarkdownContent bounded streaming cadence", () => {
  it("commits at most once per 50ms and flushes exact completed content", async () => {
    rs.useFakeTimers();
    const content = "x".repeat(200);
    const { container, rerender } = render(
      <MarkdownContent content={content} isLoading={true} />,
    );

    expect(container.textContent).toBe("");
    act(() => {
      void rs.advanceTimersByTime(49);
    });
    expect(container.textContent).toBe("");
    act(() => {
      void rs.advanceTimersByTime(1);
    });
    const firstCommitLength = container.textContent?.length ?? 0;
    expect(firstCommitLength).toBeGreaterThanOrEqual(64);
    expect(firstCommitLength).toBeLessThan(200);

    act(() => {
      void rs.advanceTimersByTime(49);
    });
    expect(container.textContent).toHaveLength(firstCommitLength);

    act(() =>
      rerender(<MarkdownContent content={content} isLoading={false} />),
    );
    expect(container.textContent).toBe(content);
  });

  it("never commits a reveal prefix that splits a surrogate pair", () => {
    rs.useFakeTimers();
    // 182 UTF-16 units; the second commit boundary lands on unit 128,
    // exactly between the emoji's two units.
    const content = `${"a".repeat(127)}😀${"b".repeat(53)}`;
    const loneSurrogate = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])/;
    const { container } = render(
      <MarkdownContent content={content} isLoading={true} />,
    );

    act(() => {
      void rs.advanceTimersByTime(50);
    });
    expect(container.textContent).toHaveLength(64);

    act(() => {
      void rs.advanceTimersByTime(50);
    });
    // The commit snapped one unit forward so the emoji stays whole.
    expect(container.textContent).toBe(`${"a".repeat(127)}😀`);
    expect(container.textContent ?? "").not.toMatch(loneSurrogate);

    act(() => {
      void rs.advanceTimersByTime(50);
    });
    expect(container.textContent).toBe(content);
  });
});

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
