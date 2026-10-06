/**
 * Wiki entry reading drawer (2026-09-05 重设计): sticky 单行头、bg-card 阅读卡、
 * 标题 H1 展示层去重，以及源切片血缘展开（entry ↔ chunk 血缘在抽屉内闭环：
 * source_chunk_ids → 只读 ChunkCard 列表，含源文档名与 #N 序号）。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

rs.mock("@/core/knowledge/hooks", () => ({
  useWikiEntry: rs.fn(),
}));

rs.mock("@/core/knowledge/api", () => ({
  listChunksByIds: rs.fn(),
  documentFileUrl: rs.fn(),
}));

import { WikiEntryDrawer } from "@/components/workspace/knowledge/wiki-entry-drawer";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { listChunksByIds } from "@/core/knowledge/api";
import { useWikiEntry } from "@/core/knowledge/hooks";
import type { KnowledgeChunkWithDoc, WikiEntryDetail } from "@/core/knowledge/types";

const DETAIL: WikiEntryDetail = {
  id: "entry-1",
  kb_id: "kb-1",
  title: "复制算法",
  content: "# 复制算法\n\n正文第一段。",
  supplement_content: null,
  status: "ready",
  source_chunk_ids: ["doc-1#0000", "doc-1#0001"],
  updated_at: "2026-08-10T08:00:00Z",
};

function chunk(index: number): KnowledgeChunkWithDoc {
  return {
    chunk_id: `doc-1#${String(index).padStart(4, "0")}`,
    doc_id: "doc-1",
    kb_id: "kb-1",
    chunk_index: index,
    text: `源切片${index}`,
    heading_path: [`h${index}`],
    page: index + 1,
    token_count: 8,
    entities: [],
    extract_status: "done",
    last_edited_at: null,
    doc_name: "a.md",
  };
}

function renderDrawer() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <WikiEntryDrawer kbId="kb-1" entryId="entry-1" open onOpenChange={() => undefined} />
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("WikiEntryDrawer", () => {
  it("dedupes the title H1 from the markdown body", async () => {
    rs.mocked(useWikiEntry).mockReturnValue({ data: DETAIL, isLoading: false } as never);
    renderDrawer();
    // 头部标题仅一次：正文同名的 `# 复制算法` 被展示层剥掉。
    expect(await screen.findAllByText("复制算法")).toHaveLength(1);
    expect(screen.getByText(/正文第一段/)).toBeTruthy();
  });

  it("expands the source-chunk lineage into read-only chunk cards", async () => {
    rs.mocked(useWikiEntry).mockReturnValue({ data: DETAIL, isLoading: false } as never);
    rs.mocked(listChunksByIds).mockResolvedValue([chunk(0), chunk(1)]);
    renderDrawer();

    fireEvent.click(await screen.findByRole("button", { name: /2 个源切片/ }));

    expect(await screen.findByText("源切片0")).toBeTruthy();
    expect(screen.getByText("源切片1")).toBeTruthy();
    // 血缘卡带源文档名与 #N 序号。
    expect(screen.getAllByText("a.md")).toHaveLength(2);
    expect(screen.getByText("#1")).toBeTruthy();
    expect(screen.getByText("#2")).toBeTruthy();
    expect(listChunksByIds).toHaveBeenCalledWith("kb-1", DETAIL.source_chunk_ids);
  });

  it("reports deleted source chunks via the count delta", async () => {
    rs.mocked(useWikiEntry).mockReturnValue({ data: DETAIL, isLoading: false } as never);
    rs.mocked(listChunksByIds).mockResolvedValue([]);
    renderDrawer();

    fireEvent.click(await screen.findByRole("button", { name: /2 个源切片/ }));

    expect(await screen.findByText(/2 个源切片已删除/)).toBeTruthy();
  });
});
