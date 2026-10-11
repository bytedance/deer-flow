import { afterEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { MessageReasoning } from "@/components/workspace/messages/message-reasoning";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

function view(isLoading = false, durationSeconds?: number) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageReasoning isLoading={isLoading} durationSeconds={durationSeconds}>
        Consider the question.
      </MessageReasoning>
    </I18nContext.Provider>
  );
}

function advance(milliseconds: number) {
  act(() => {
    void rs.advanceTimersByTime(milliseconds);
  });
}

for (const durationSeconds of [undefined, 31]) {
  it(`starts completed reasoning collapsed, including remounts: ${durationSeconds}`, () => {
    rs.useFakeTimers();
    const first = render(view(false, durationSeconds));
    expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe(
      "false",
    );
    first.unmount();
    render(view(false, durationSeconds));
    expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe(
      "false",
    );
  });
}

it("keeps manually expanded history open without an auto-close timer", () => {
  rs.useFakeTimers();
  render(view(false, 31));
  const trigger = screen.getByRole("button");
  fireEvent.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  advance(2000);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
});

it("opens a later stream and closes once after completion", () => {
  rs.useFakeTimers();
  const { rerender } = render(view());
  rerender(view(true));
  const trigger = screen.getByRole("button");
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  rerender(view(false, 31));
  advance(999);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  advance(1);
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(trigger);
  advance(2000);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
});

it("preserves live completion when persisted duration replaces client time", () => {
  rs.useFakeTimers();
  const { rerender } = render(view(true));
  rerender(view(false, 31));
  advance(500);
  rerender(view(false, 47));
  advance(500);
  expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe(
    "false",
  );
  expect(screen.getByTestId("run-duration").textContent).toBe("Took 47s");
});

it("cancels a pending close when streaming resumes", () => {
  rs.useFakeTimers();
  const { rerender } = render(view(true));
  rerender(view(false, 31));
  advance(500);
  rerender(view(true));
  advance(1000);
  expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe("true");
  rerender(view(false, 47));
  advance(1000);
  expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe(
    "false",
  );
});

it("clears the close timer on unmount", () => {
  rs.useFakeTimers();
  const { rerender, unmount } = render(view(true));
  rerender(view(false, 31));
  unmount();
  expect(rs.getTimerCount()).toBe(0);
});
