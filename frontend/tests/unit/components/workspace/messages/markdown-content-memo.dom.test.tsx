import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";

const counts = rs.hoisted(() => ({ render: 0 }));

rs.mock("@/core/streamdown/components", () => ({
  SafeMessageResponse: ({ children }: { children: ReactNode }) => {
    counts.render += 1;
    return <div data-testid="markdown">{children}</div>;
  },
  toStreamdownComponents: (components: unknown) => components,
}));

import { MarkdownContent } from "@/components/workspace/messages/markdown-content";

function Parent({ content }: { content: string }) {
  const [, setTick] = useState(0);
  return (
    <>
      <button type="button" onClick={() => setTick((value) => value + 1)}>
        rerender
      </button>
      <MarkdownContent content={content} isLoading={false} />
    </>
  );
}

beforeEach(() => {
  counts.render = 0;
});
afterEach(cleanup);

it("does not re-render unchanged markdown when the parent re-renders", () => {
  const { rerender } = render(<Parent content="hello" />);
  expect(screen.getByTestId("markdown")).toBeTruthy();
  const mounted = counts.render;

  fireEvent.click(screen.getByRole("button", { name: "rerender" }));
  expect(counts.render).toBe(mounted);

  rerender(<Parent content="changed" />);
  expect(counts.render).toBeGreaterThan(mounted);
});
