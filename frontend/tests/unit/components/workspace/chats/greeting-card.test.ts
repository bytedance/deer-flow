/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GreetingCard } from "@/components/workspace/chats/greeting-card";

vi.mock("@/components/ui/icons", () => ({
  BotIcon: () => React.createElement("span", null, "bot"),
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: (props: Record<string, unknown>) =>
    React.createElement("div", props),
}));

describe("GreetingCard", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("keeps the greeting visible and hides suggestion chips", () => {
    const onSuggestionClick = vi.fn();

    React.act(() => {
      root.render(
        React.createElement(GreetingCard, {
          greeting: "早上好！有什么我可以帮您的吗？",
          suggestions: ["分析异常趋势", "查看设备状态"],
          onSuggestionClick,
        }),
      );
    });

    expect(container.textContent).toContain("早上好！有什么我可以帮您的吗？");
    expect(container.textContent).not.toContain("分析异常趋势");
    expect(container.textContent).not.toContain("查看设备状态");
    expect(container.querySelectorAll("button").length).toBe(0);
    expect(onSuggestionClick).not.toHaveBeenCalled();
  });
});
