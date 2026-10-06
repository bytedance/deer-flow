/**
 * Citation cards under an assistant answer (spec §4.6/§3.6; phase-2 batch-1
 * P2 reworked the strip: collapsed one-line entry by default, expanding
 * shows merged cards). These cases keep the phase-1 in-place ChunkCard
 * expand/collapse behaviour honest under the new interaction.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { KbCitationSources } from "@/components/workspace/knowledge/kb-citation-sources";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeCitation } from "@/core/knowledge/types";

const SOURCES: KnowledgeCitation[] = [
  {
    chunk_id: "doc-1#0000",
    doc_name: "产品手册.pdf",
    page: 3,
    heading_path: ["第一章"],
    text: "知识库系统将非结构化文档转化为可检索的知识资产。",
    score: 0.87,
  },
  {
    chunk_id: "doc-2#0003",
    doc_name: "架构设计.md",
    page: null,
    heading_path: [],
    text: "Gateway 通过 Nginx 反向代理对外提供统一入口。",
    score: 0.76,
  },
];

function renderWithI18n(node: React.ReactNode) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      {node}
    </I18nContext.Provider>,
  );
}

function renderSources(sources: KnowledgeCitation[] = SOURCES) {
  renderWithI18n(<KbCitationSources messageId="m1" sources={sources} />);
  // P2: the strip is collapsed by default — open it to reach the cards.
  fireEvent.click(screen.getByText(/参考来源 ·/));
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("KbCitationSources", () => {
  it("collapsed by default; expanding reveals numbered cards with doc name and page", () => {
    renderWithI18n(<KbCitationSources messageId="m1" sources={SOURCES} />);
    expect(screen.getByText(/参考来源 · 2/)).toBeTruthy();
    expect(screen.queryByText("产品手册.pdf")).toBeNull();

    fireEvent.click(screen.getByText(/参考来源 · 2/));
    expect(screen.getByText("[1]")).toBeTruthy();
    expect(screen.getByText("[2]")).toBeTruthy();
    expect(screen.getByText("产品手册.pdf")).toBeTruthy();
    expect(screen.getByText("架构设计.md")).toBeTruthy();
    expect(screen.getByText(/第 3 页/)).toBeTruthy();
  });

  it("renders nothing when there are no sources", () => {
    const { container } = renderWithI18n(<KbCitationSources messageId="m1" sources={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("expands the shared chunk card with the original text on click", () => {
    renderSources();
    // collapsed: only the card's in-place excerpt carries the text (once)
    expect(screen.getAllByText(SOURCES[0]!.text)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /产品手册\.pdf/ }));
    // expanded: excerpt + ChunkCard full text
    expect(screen.getAllByText(SOURCES[0]!.text)).toHaveLength(2);
    // The other source stays collapsed.
    expect(screen.getAllByText(SOURCES[1]!.text)).toHaveLength(1);
  });

  it("collapses the expanded chunk when the same source is clicked again", () => {
    renderSources();
    fireEvent.click(screen.getByRole("button", { name: /产品手册\.pdf/ }));
    expect(screen.getAllByText(SOURCES[0]!.text)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /产品手册\.pdf/ }));
    expect(screen.getAllByText(SOURCES[0]!.text)).toHaveLength(1);
  });

  it("switches the expanded chunk when another source is clicked", () => {
    renderSources();
    fireEvent.click(screen.getByRole("button", { name: /产品手册\.pdf/ }));
    fireEvent.click(screen.getByRole("button", { name: /架构设计\.md/ }));
    expect(screen.getAllByText(SOURCES[0]!.text)).toHaveLength(1);
    expect(screen.getAllByText(SOURCES[1]!.text)).toHaveLength(2);
  });
});
