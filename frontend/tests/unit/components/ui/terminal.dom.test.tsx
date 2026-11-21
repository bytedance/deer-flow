import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";

import { TypingAnimation } from "@/components/ui/terminal";

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("TypingAnimation", () => {
  it("reveals astral characters without rendering a lone surrogate", () => {
    rs.useFakeTimers();
    const text = `A\u{1f600}B`;
    const { container } = render(
      <TypingAnimation duration={10} startOnView={false}>
        {text}
      </TypingAnimation>,
    );

    act(() => {
      void rs.advanceTimersByTime(0);
    });
    act(() => {
      void rs.advanceTimersByTime(10);
    });
    expect(container.textContent).toBe("A");

    act(() => {
      void rs.advanceTimersByTime(10);
    });
    expect(container.textContent).toBe(`A\u{1f600}`);

    act(() => {
      void rs.advanceTimersByTime(10);
    });
    expect(container.textContent).toBe(text);
  });
});
