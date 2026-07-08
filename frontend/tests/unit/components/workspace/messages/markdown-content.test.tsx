/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/ai-elements/message", () => ({
  MessageResponse: ({ children }: { children: string }) =>
    React.createElement("div", { "data-testid": "message-response" }, children),
}));

vi.mock("../citations/citation-link", () => ({
  CitationLink: () =>
    React.createElement("span", { "data-testid": "citation-link" }),
}));

vi.mock("../citations/kb-citation-link", () => ({
  KBCitationLink: () =>
    React.createElement("span", { "data-testid": "kb-citation-link" }),
}));

import { MarkdownContent } from "@/components/workspace/messages/markdown-content";

describe("MarkdownContent", () => {
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
    root.unmount();
    document.body.removeChild(container);
  });

  it("accepts sources prop without throwing", () => {
    expect(() => {
      root.render(
        <MarkdownContent
          content="Test content"
          isLoading={false}
          rehypePlugins={[]}
          sources={[
            {
              kb_id: "kb-001",
              kb_name: "故障处理手册",
              doc_title: "温度故障处理",
              score: 0.85,
            },
          ]}
        />,
      );
    }).not.toThrow();
  });

  it("accepts null sources without throwing", () => {
    expect(() => {
      root.render(
        <MarkdownContent
          content="Test content"
          isLoading={false}
          rehypePlugins={[]}
          sources={null}
        />,
      );
    }).not.toThrow();
  });

  it("returns null for empty content", () => {
    root.render(
      <MarkdownContent content="" isLoading={false} rehypePlugins={[]} />,
    );

    expect(container.firstChild).toBeNull();
  });
});
