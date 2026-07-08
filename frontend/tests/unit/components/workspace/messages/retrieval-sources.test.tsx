/* @vitest-environment jsdom */

import type { Message } from "@langchain/langgraph-sdk";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/badge", () => ({
  Badge: ({
    children,
    className,
  }: React.PropsWithChildren<{ className?: string }>) =>
    React.createElement(
      "span",
      { "data-testid": "badge", className },
      children,
    ),
}));

vi.mock("@/components/ui/icons", () => ({
  BookOpenIcon: ({ className }: { className?: string }) =>
    React.createElement("span", { className, "data-testid": "book-open-icon" }),
  ChevronDownIcon: ({ className }: { className?: string }) =>
    React.createElement("span", {
      className,
      "data-testid": "chevron-down-icon",
    }),
}));

import { RetrievalSources } from "@/components/workspace/messages/retrieval-sources";
import type { RetrievalSource } from "@/core/messages/utils";

function makeTraceMessage(sources: RetrievalSource[]): Message {
  const trace = JSON.stringify({ sources });
  return {
    type: "ai",
    content: `<retrieval_trace>${trace}</retrieval_trace>`,
    id: "ai-1",
  } as Message;
}

describe("RetrievalSources score display", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    document.body.removeChild(container);
  });

  it("displays relevance score formatted to two decimal places", () => {
    const messages: Message[] = [
      makeTraceMessage([
        {
          kb_id: "kb-001",
          kb_name: "故障处理手册",
          doc_title: "温度故障处理",
          score: 0.8523,
        },
      ]),
    ];

    act(() => {
      root.render(<RetrievalSources messages={messages} />);
    });

    const button = container.querySelector("button");
    expect(button).not.toBeNull();
    act(() => {
      button!.click();
    });

    const text = container.textContent ?? "";
    expect(text).toContain("0.85");
  });

  it("displays score for each source when multiple sources exist", () => {
    const messages: Message[] = [
      makeTraceMessage([
        {
          kb_id: "kb-001",
          kb_name: "故障处理手册",
          doc_title: "温度故障处理",
          score: 0.85,
        },
        {
          kb_id: "kb-002",
          kb_name: "设备维护知识库",
          doc_title: "振动告警处理",
          score: 0.92,
        },
      ]),
    ];

    act(() => {
      root.render(<RetrievalSources messages={messages} />);
    });

    const button = container.querySelector("button");
    act(() => {
      button!.click();
    });

    const text = container.textContent ?? "";
    expect(text).toContain("0.85");
    expect(text).toContain("0.92");
  });

  it("returns null when no retrieval trace exists", () => {
    const messages: Message[] = [];

    act(() => {
      root.render(<RetrievalSources messages={messages} />);
    });

    const button = container.querySelector("button");
    expect(button).toBeNull();
  });
});
