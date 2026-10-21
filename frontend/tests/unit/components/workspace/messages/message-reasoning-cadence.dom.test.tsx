import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";

import { MessageReasoning } from "@/components/workspace/messages/message-reasoning";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const rendered = rs.hoisted(() => ({ values: [] as string[] }));

rs.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: string }) => {
    rendered.values.push(children);
    return <div data-testid="reasoning-markdown">{children}</div>;
  },
}));

beforeEach(() => {
  rs.useFakeTimers();
  rendered.values.length = 0;
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

function view(content: string, isLoading = true) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageReasoning isLoading={isLoading}>{content}</MessageReasoning>
    </I18nContext.Provider>
  );
}

function advance(milliseconds: number) {
  act(() => {
    void rs.advanceTimersByTime(milliseconds);
  });
}

it("coalesces rapid reasoning updates before Markdown rendering", () => {
  let content = "Thinking";
  const { rerender } = render(view(content));
  expect(rendered.values).toEqual([content]);

  for (let index = 0; index < 10; index += 1) {
    content += ` step${index}`;
    rerender(view(content));
    advance(4);
  }

  expect(rendered.values).toEqual(["Thinking"]);
  advance(9);
  expect(rendered.values).toHaveLength(1);
  advance(1);
  expect(rendered.values).toEqual(["Thinking", content]);
  expect(screen.getByTestId("reasoning-markdown").textContent).toBe(content);
});

it("keeps making progress during a continuous reasoning stream", () => {
  let content = "Thinking";
  const { rerender } = render(view(content));

  for (let index = 0; index < 20; index += 1) {
    content += ` step${index}`;
    rerender(view(content));
    advance(5);
  }

  expect(rendered.values).toHaveLength(3);
  expect(rendered.values[1]).toContain("step9");
  expect(rendered.values[2]).toBe(content);
});

it("flushes the exact final reasoning immediately on completion", () => {
  const { rerender } = render(view("Thinking"));
  rerender(view("Thinking with a pending update"));
  advance(20);
  rerender(view("Thinking with the exact final answer.", false));

  expect(screen.getByTestId("reasoning-markdown").textContent).toBe(
    "Thinking with the exact final answer.",
  );
  advance(100);
  expect(rendered.values.at(-1)).toBe("Thinking with the exact final answer.");
});

it("shows replacement text immediately instead of retaining another message", () => {
  const { rerender } = render(view("Previous reasoning"));
  rerender(view("Previous reasoning pending"));
  advance(20);
  rerender(view("Replacement reasoning"));

  expect(screen.getByTestId("reasoning-markdown").textContent).toBe(
    "Replacement reasoning",
  );
  advance(100);
  expect(rendered.values.at(-1)).toBe("Replacement reasoning");
});

it("cancels pending rendering work on unmount", () => {
  const { rerender, unmount } = render(view("Thinking"));
  rerender(view("Thinking with a pending update"));
  unmount();

  expect(rs.getTimerCount()).toBe(0);
});
