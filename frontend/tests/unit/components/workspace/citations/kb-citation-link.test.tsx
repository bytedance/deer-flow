/* @vitest-environment jsdom */

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/badge", () => ({
  Badge: ({
    children,
    className,
    ...props
  }: React.PropsWithChildren<{ className?: string }>) =>
    React.createElement(
      "span",
      { "data-testid": "badge", className, ...props },
      children,
    ),
}));

vi.mock("@/components/ui/hover-card", () => ({
  HoverCard: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", { "data-testid": "hover-card" }, children),
  HoverCardTrigger: ({ children }: React.PropsWithChildren) =>
    React.createElement(
      "div",
      { "data-testid": "hover-card-trigger" },
      children,
    ),
  HoverCardContent: ({
    children,
    className,
  }: React.PropsWithChildren<{ className?: string }>) =>
    React.createElement(
      "div",
      { "data-testid": "hover-card-content", className },
      children,
    ),
}));

import { KBCitationLink } from "@/components/workspace/citations/kb-citation-link";
import type { RetrievalSource } from "@/core/messages/utils";

const MOCK_SOURCES: RetrievalSource[] = [
  {
    kb_id: "kb-001",
    kb_name: "故障处理手册",
    doc_title: "温度故障处理",
    score: 0.8523,
  },
  {
    kb_id: "kb-002",
    kb_name: "设备维护知识库",
    doc_title: "振动告警处理",
    score: 0.921,
  },
];

describe("KBCitationLink", () => {
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

  it("renders a blue badge with children text when source is found", () => {
    act(() => {
      root.render(
        <KBCitationLink href="kb://kb-001" sources={MOCK_SOURCES}>
          kb:温度故障处理
        </KBCitationLink>,
      );
    });

    const badge = container.querySelector('[data-testid="badge"]');
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("kb:温度故障处理");
  });

  it("shows hover card content with doc_title, kb_name, and score when source matches", () => {
    act(() => {
      root.render(
        <KBCitationLink href="kb://kb-001" sources={MOCK_SOURCES}>
          kb:温度故障处理
        </KBCitationLink>,
      );
    });

    const hoverContent = container.querySelector(
      '[data-testid="hover-card-content"]',
    );
    expect(hoverContent).not.toBeNull();
    expect(hoverContent!.textContent).toContain("温度故障处理");
    expect(hoverContent!.textContent).toContain("故障处理手册");
    expect(hoverContent!.textContent).toContain("0.85");
  });

  it("degrades to plain badge when kb_id does not match any source", () => {
    act(() => {
      root.render(
        <KBCitationLink href="kb://kb-999" sources={MOCK_SOURCES}>
          kb:不存在文档
        </KBCitationLink>,
      );
    });

    const badge = container.querySelector('[data-testid="badge"]');
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("kb:不存在文档");
    const hoverCard = container.querySelector('[data-testid="hover-card"]');
    expect(hoverCard).toBeNull();
  });

  it("degrades to plain badge when sources is null", () => {
    act(() => {
      root.render(
        <KBCitationLink href="kb://kb-001" sources={null}>
          kb:温度故障处理
        </KBCitationLink>,
      );
    });

    const badge = container.querySelector('[data-testid="badge"]');
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("kb:温度故障处理");
    const hoverCard = container.querySelector('[data-testid="hover-card"]');
    expect(hoverCard).toBeNull();
  });

  it("degrades to plain badge when sources is undefined", () => {
    act(() => {
      root.render(
        <KBCitationLink href="kb://kb-001">kb:温度故障处理</KBCitationLink>,
      );
    });

    const badge = container.querySelector('[data-testid="badge"]');
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("kb:温度故障处理");
    const hoverCard = container.querySelector('[data-testid="hover-card"]');
    expect(hoverCard).toBeNull();
  });

  it("renders as span element, not anchor", () => {
    act(() => {
      root.render(
        <KBCitationLink href="kb://kb-001" sources={MOCK_SOURCES}>
          kb:温度故障处理
        </KBCitationLink>,
      );
    });

    const anchors = container.querySelectorAll("a");
    expect(anchors.length).toBe(0);
  });
});
