/**
 * Citation UX (phase-2 batch-1, P2): superscript marks in the answer body
 * (deferred until streaming ends), a hover preview card, and the sources
 * strip collapsed by default into a one-line entry「参考来源 · N + 类型统计」.
 * Expanded cards merge same-document citations (numbers combined) and cap at
 * 5 with 查看全部. Mark clicks dispatch a jump event that expands the strip
 * and highlights the matching card.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

rs.mock("@/components/workspace/messages/markdown-content", () => ({
  // 渲染 content 而不是 null：ChunkCard 查看态改走 MarkdownContent 后
  // （2026-08-22 展示增强），展开断言依赖全文真实出现在 DOM 里；
  // rs.fn 保留调用记录供 KbAssistantContent 断言 props。
  MarkdownContent: rs.fn(({ content }: { content: string }) => <div data-testid="mock-markdown-content">{content}</div>),
}));

import { CitationMark, CitationPreviewCard, createCitationSupRenderer, KB_CITATION_JUMP_EVENT } from "@/components/workspace/knowledge/citation-mark";
import { KbAssistantContent } from "@/components/workspace/knowledge/kb-assistant-content";
import { KbCitationSources } from "@/components/workspace/knowledge/kb-citation-sources";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeCitation } from "@/core/knowledge/types";

const CHUNK_1: KnowledgeCitation = {
  chunk_id: "c1",
  doc_name: "手册.pdf",
  page: 3,
  heading_path: ["第一章"],
  text: "切片原文一，足够长的内容用来验证摘录截断。" + "长".repeat(150),
  score: 0.9,
  source_type: "chunk",
};
const CHUNK_2_SAME_DOC: KnowledgeCitation = {
  chunk_id: "c2",
  doc_name: "手册.pdf",
  page: 5,
  heading_path: ["第二章"],
  text: "切片原文二。",
  score: 0.8,
  source_type: "chunk",
};
const SECOND_1: KnowledgeCitation = {
  chunk_id: "e1",
  doc_name: "DeerFlow",
  page: null,
  heading_path: [],
  text: "条目全文内容。",
  score: 0.7,
  source_type: "chunk",
};

function renderWithI18n(node: React.ReactNode) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      {node}
    </I18nContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("CitationMark", () => {
  it("renders a superscript button with an accessible label (quiet grey step)", () => {
    const Sup = createCitationSupRenderer([CHUNK_1], "m1");
    renderWithI18n(<Sup data-citation-index="1">1</Sup>);
    const mark = screen.getByRole("button", { name: "引用 1：手册.pdf" });
    expect(mark.className).toContain("align-super");
    // 裁定④：默认极小极淡（不注意看看不出来）、无常驻底色，hover 才浮出胶囊
    expect(mark.className).toContain("text-[0.3em]");
    expect(mark.className).toContain("text-muted-foreground/70");
    expect(mark.className).toContain("hover:text-foreground");
    expect(mark.className).not.toContain("bg-muted/40");
  });

  it("falls back to a plain sup for unknown indexes (no crash on stale marks)", () => {
    const Sup = createCitationSupRenderer([CHUNK_1], "m1");
    const { container } = renderWithI18n(<Sup data-citation-index="9">9</Sup>);
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelector("sup")).not.toBeNull();
  });

  it("renders the chunk hover preview with its type badge", () => {
    renderWithI18n(<CitationPreviewCard citation={CHUNK_1} />);
    const preview = screen.getByTestId("citation-preview");
    expect(preview.textContent).toContain("文档");
    expect(preview.textContent).toContain("手册.pdf");
    expect(preview.textContent).toContain("切片原文一");
  });

  it("dispatches the jump event with messageId + indices on click", () => {
    const listener = rs.fn();
    window.addEventListener(KB_CITATION_JUMP_EVENT, listener);
    try {
      renderWithI18n(<CitationMark items={[{ citation: SECOND_1, index: 2 }]} messageId="m1" />);
      fireEvent.click(screen.getByRole("button"));
      expect(listener).toHaveBeenCalled();
      expect(listener.mock.calls[0]![0].detail).toEqual({ messageId: "m1", indices: [2] });
    } finally {
      window.removeEventListener(KB_CITATION_JUMP_EVENT, listener);
    }
  });

  it("maps the model's citation_no to the display number (sorted card position)", () => {
    // Production overlap: the model wrote backend citation_no [9], which
    // merged onto the sample chunk whose sorted position is 2 — the mark must
    // show/jump the DISPLAY number 2, never the raw 9 (Perplexity-style: the
    // visible number space is the deduped, sorted card list).
    const second: KnowledgeCitation = { ...SECOND_1, citation_nos: [1] };
    const chunk: KnowledgeCitation = { ...CHUNK_1, citation_nos: [5, 9] };
    const listener = rs.fn();
    window.addEventListener(KB_CITATION_JUMP_EVENT, listener);
    try {
      const Sup = createCitationSupRenderer([second, chunk], "m1");
      renderWithI18n(<Sup data-citation-index="9">9</Sup>);
      const mark = screen.getByRole("button", { name: "引用 2：手册.pdf" });
      expect(mark.textContent).toBe("2");
      fireEvent.click(mark);
      expect(listener.mock.calls[0]![0].detail).toEqual({ messageId: "m1", indices: [2] });
    } finally {
      window.removeEventListener(KB_CITATION_JUMP_EVENT, listener);
    }
  });

  it("renders a merged group as one pill, display numbers sorted ascending and deduped (裁定③)", () => {
    const first: KnowledgeCitation = { ...SECOND_1, citation_nos: [5] };
    const second: KnowledgeCitation = { ...CHUNK_1, citation_nos: [9] };
    const listener = rs.fn();
    window.addEventListener(KB_CITATION_JUMP_EVENT, listener);
    try {
      const Sup = createCitationSupRenderer([first, second], "m1");
      renderWithI18n(<Sup data-citation-indices="9 5 9">9 5 9</Sup>);
      expect(screen.getAllByRole("button")).toHaveLength(1);
      const mark = screen.getByRole("button");
      // raw 9 → display 2, raw 5 → display 1 ⇒ sorted "1,2" (never "2,1" or "2,1,2")
      expect(mark.textContent).toBe("1,2");
      expect(mark.getAttribute("aria-label")).toBe("引用 1：DeerFlow; 引用 2：手册.pdf");
      fireEvent.click(mark);
      expect(listener.mock.calls[0]![0].detail).toEqual({ messageId: "m1", indices: [1, 2] });
    } finally {
      window.removeEventListener(KB_CITATION_JUMP_EVENT, listener);
    }
  });

  it("keeps the pill for resolvable numbers and plain sups for stale ones (mixed group)", () => {
    const chunk: KnowledgeCitation = { ...CHUNK_1, citation_nos: [9] };
    const Sup = createCitationSupRenderer([chunk], "m1");
    const { container } = renderWithI18n(<Sup data-citation-indices="9 7">9 7</Sup>);
    const mark = screen.getByRole("button");
    expect(mark.textContent).toBe("1");
    const plain = container.querySelectorAll("sup");
    expect(plain).toHaveLength(1);
    expect(plain[0]!.textContent).toBe("7");
  });
});

describe("KbAssistantContent (deferred superscripts)", () => {
  function markdownProps() {
    return (MarkdownContent as unknown as ReturnType<typeof rs.fn>).mock.calls[0]?.[0];
  }

  it("enables the citation plugin only after streaming ends", () => {
    renderWithI18n(<KbAssistantContent content="回答 [1]" isLoading={true} messageId="m1" sources={[CHUNK_1]} />);
    expect(markdownProps().rehypePlugins ?? []).toHaveLength(0);

    cleanup();
    rs.clearAllMocks();

    renderWithI18n(<KbAssistantContent content="回答 [1]" isLoading={false} messageId="m1" sources={[CHUNK_1]} />);
    const props = markdownProps();
    expect(props.rehypePlugins).toHaveLength(1);
    expect(props.components.sup).toBeTypeOf("function");
  });
});

describe("KbCitationSources (collapsed by default)", () => {
  it("renders a one-line collapsed entry with the chunk count", () => {
    renderWithI18n(<KbCitationSources messageId="m1" sources={[CHUNK_1, SECOND_1]} />);
    expect(screen.getByText(/参考来源 · 2/)).toBeTruthy();
    expect(screen.getByText(/文档×2/)).toBeTruthy();
    // collapsed: no source cards yet
    expect(screen.queryByText("切片原文二。")).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("expands into merged cards (same document combined, numbers shown together)", () => {
    renderWithI18n(<KbCitationSources messageId="m1" sources={[CHUNK_1, CHUNK_2_SAME_DOC, SECOND_1]} />);
    fireEvent.click(screen.getByText(/参考来源 · 3/));
    // two cards: 手册.pdf merges [1]+[2]; DeerFlow is [3]
    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(cards[0]!.textContent).toContain("[1]·[2]");
    expect(cards[0]!.textContent).toContain("手册.pdf");
    expect(cards[0]!.textContent).toContain("文档");
    expect(cards[1]!.textContent).toContain("DeerFlow");
    expect(cards[1]!.textContent).toContain("文档");
    // excerpt truncated to ~120 chars
    expect(cards[0]!.textContent?.length ?? 0).toBeLessThan(CHUNK_1.text.length + 60);
  });

  it("caps at 5 cards and reveals the rest via 查看全部", () => {
    const many: KnowledgeCitation[] = Array.from({ length: 6 }, (_, index) => ({
      ...CHUNK_1,
      chunk_id: `c${index + 1}`,
      doc_name: `文档${index + 1}.md`,
    }));
    renderWithI18n(<KbCitationSources messageId="m1" sources={many} />);
    fireEvent.click(screen.getByText(/参考来源 · 6/));
    // 5 source cards + the 查看全部 row (an li of its own)
    expect(screen.getAllByTestId(/citation-card-/)).toHaveLength(5);
    fireEvent.click(screen.getByText(/查看全部/));
    expect(screen.getAllByTestId(/citation-card-/)).toHaveLength(6);
  });

  it("treats legacy citations without source_type as chunk", () => {
    const legacy: KnowledgeCitation = { ...CHUNK_1 };
    delete legacy.source_type;
    renderWithI18n(<KbCitationSources messageId="m1" sources={[legacy]} />);
    expect(screen.getByText(/文档×1/)).toBeTruthy();
    expect(screen.queryByText(/百科×/)).toBeNull();
  });

  it("reacts to a jump event for its own message: expands, highlights, auto-opens the chunk", () => {
    renderWithI18n(<KbCitationSources messageId="m1" sources={[CHUNK_1]} />);
    expect(screen.queryByRole("list")).toBeNull();
    act(() => {
      window.dispatchEvent(new CustomEvent(KB_CITATION_JUMP_EVENT, { detail: { messageId: "m1", indices: [1] } }));
    });
    const highlighted = screen.getByTestId("citation-card-chunk-c1");
    expect(highlighted.getAttribute("data-citation-highlight")).toBe("true");
    // chunk card auto-expanded (移动端 tap 直接展开切片)
    expect(screen.getAllByText(/切片原文一/).length).toBeGreaterThanOrEqual(2);
  });

  it("highlights every matching card for a merged mark (裁定②)", () => {
    renderWithI18n(<KbCitationSources messageId="m1" sources={[CHUNK_1, SECOND_1]} />);
    act(() => {
      window.dispatchEvent(new CustomEvent(KB_CITATION_JUMP_EVENT, { detail: { messageId: "m1", indices: [1, 2] } }));
    });
    expect(screen.getByTestId("citation-card-chunk-c1").getAttribute("data-citation-highlight")).toBe("true");
    expect(screen.getByTestId("citation-card-chunk-e1").getAttribute("data-citation-highlight")).toBe("true");
  });

  it("shows display numbers (sorted positions) even when citations carry backend citation_nos", () => {
    // The card must show its display number [1] — not the merged backend
    // numbers [4]·[9] — so the visible number space stays 1..N continuous.
    const chunk: KnowledgeCitation = { ...CHUNK_1, citation_nos: [4, 9] };
    renderWithI18n(<KbCitationSources messageId="m1" sources={[chunk]} />);
    fireEvent.click(screen.getByText(/参考来源 · 1/));
    const card = screen.getByTestId("citation-card-chunk-c1");
    expect(card.textContent).toContain("[1]");
    expect(card.textContent).not.toContain("[4]");
    expect(card.textContent).not.toContain("[9]");
  });

  it("ignores jump events for other messages", () => {
    renderWithI18n(<KbCitationSources messageId="m1" sources={[CHUNK_1]} />);
    act(() => {
      window.dispatchEvent(new CustomEvent(KB_CITATION_JUMP_EVENT, { detail: { messageId: "other", indices: [1] } }));
    });
    expect(screen.queryByRole("list")).toBeNull();
  });
});
