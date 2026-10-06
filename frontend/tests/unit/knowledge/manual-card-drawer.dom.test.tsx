/**
 * Manual knowledge card detail drawer (Phase-3 P6 fix): the card counterpart
 * of WikiEntryDrawer. Recall-test wiki-path hits can be manual cards (spec §8
 * 混排) — clicking one must open THIS drawer via the card id, not the wiki
 * entry drawer (whose detail endpoint 404s on card ids, surfacing as
 * 「条目不存在或已删除」). Renders title / tags / full content / updated_at.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

rs.mock("@/core/knowledge/hooks", () => ({
  useManualCard: rs.fn(),
}));

import { ManualCardDrawer } from "@/components/workspace/knowledge/manual-card-drawer";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { cardDrawersKey } from "@/core/knowledge/card-drawers";
import { useManualCard } from "@/core/knowledge/hooks";
import type { ManualCardDetail } from "@/core/knowledge/types";

const CARD: ManualCardDetail = {
  id: "card-1",
  kb_id: "kb-1",
  owner_id: "u1",
  title: "发布禁令",
  content: "周五下午不发布，紧急修复走审批。",
  tags: ["流程", "发布"],
  include_in_wiki_search: true,
  created_at: "2026-08-15T08:00:00Z",
  updated_at: "2026-08-15T09:30:00Z",
};

function mockCard(overrides?: { data?: ManualCardDetail | null; isLoading?: boolean }) {
  (useManualCard as unknown as ReturnType<typeof rs.fn>).mockReturnValue({
    data: overrides?.data ?? null,
    isLoading: overrides?.isLoading ?? false,
  });
}

function renderDrawer(props?: Partial<Parameters<typeof ManualCardDrawer>[0]>) {
  const onOpenChange = rs.fn();
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <ManualCardDrawer cardId="card-1" kbId="kb-1" open={true} onOpenChange={onOpenChange} {...props} />
    </I18nContext.Provider>,
  );
  return { onOpenChange };
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("ManualCardDrawer", () => {
  it("shows the loading state while fetching", () => {
    mockCard({ isLoading: true });
    renderDrawer();
    expect(screen.getAllByText("加载中…").length).toBeGreaterThanOrEqual(1);
  });

  it("renders title, tags, full content and the mixed-search badge", () => {
    mockCard({ data: CARD });
    renderDrawer();
    expect(screen.getByText("发布禁令")).toBeTruthy();
    expect(screen.getByText("周五下午不发布，紧急修复走审批。")).toBeTruthy();
    expect(screen.getByText("流程")).toBeTruthy();
    expect(screen.getByText("发布")).toBeTruthy();
    expect(screen.getByText(/混入搜索/)).toBeTruthy();
  });

  it("shows 卡片不存在或已删除 when the fetch resolves to null", () => {
    mockCard({ data: null, isLoading: false });
    renderDrawer();
    expect(screen.getByText("卡片不存在或已删除")).toBeTruthy();
  });

  it("passes null ids to the query while closed (no fetch)", () => {
    mockCard();
    renderDrawer({ open: false });
    expect(useManualCard).toHaveBeenCalledWith(null, null);
  });

  it("adapts the header glyph + name chip to the card's drawer (2026-09-05)", () => {
    // 卡片可在抽屉间移动：头部图标/名称跟随 membership 当前归属。
    localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [{ id: "dw-1", name: "工作笔记", icon: "star", color: "amber" }],
        membership: { "card-1": "dw-1" },
      }),
    );
    mockCard({ data: CARD });
    renderDrawer();
    expect(screen.getByText("工作笔记")).toBeTruthy();
    localStorage.removeItem(cardDrawersKey("kb-1"));
  });

  it("falls back to the neutral note glyph when the card is unfiled", () => {
    mockCard({ data: CARD });
    renderDrawer();
    expect(screen.queryByText("工作笔记")).toBeNull();
  });
});
