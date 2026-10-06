/**
 * Wiki tab container (split-section layout): one unified search box above the
 * AI entries section and the manual-cards section. Typing one query filters
 * both sections (and force-expands/fetches the collapsed cards section); the
 * clear button restores both lists.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

rs.mock("@/core/knowledge/hooks", () => ({
  useManualCards: rs.fn(),
  useManualCard: rs.fn(),
  useCreateManualCard: rs.fn(),
  useUpdateManualCard: rs.fn(),
  useDeleteManualCard: rs.fn(),
}));

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn() },
}));

import { WikiTab } from "@/components/workspace/knowledge/wiki-tab";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  useCreateManualCard,
  useDeleteManualCard,
  useManualCard,
  useManualCards,
  useUpdateManualCard,
} from "@/core/knowledge/hooks";
import type { WikiEntrySummary } from "@/core/knowledge/types";

const ENTRIES: WikiEntrySummary[] = [
  {
    id: "e1",
    title: "DeerFlow",
    summary: "超级代理系统",
    status: "ready",
    updated_at: "2026-08-10T08:00:00Z",
  },
  {
    id: "e2",
    title: "Gateway",
    summary: "网关负责统一鉴权",
    status: "ready",
    updated_at: "2026-08-10T09:00:00Z",
  },
];

function setupMocks() {
  rs.mocked(useManualCards).mockReturnValue({
    data: {
      items: [
        {
          id: "card-1",
          title: "发布禁令",
          summary: "周五下午不发布",
          tags: [],
          include_in_wiki_search: false,
          created_at: "2026-08-15T10:00:00Z",
          updated_at: "2026-08-15T10:00:00Z",
        },
      ],
      total: 1,
      offset: 0,
      limit: 50,
    },
    isLoading: false,
  } as never);
  rs.mocked(useManualCard).mockReturnValue({ data: null } as never);
  rs.mocked(useCreateManualCard).mockReturnValue({
    mutateAsync: rs.fn(),
    isPending: false,
  } as never);
  rs.mocked(useUpdateManualCard).mockReturnValue({
    mutateAsync: rs.fn(),
    isPending: false,
  } as never);
  rs.mocked(useDeleteManualCard).mockReturnValue({
    mutateAsync: rs.fn(),
    isPending: false,
  } as never);
}

function renderTab(props?: Partial<Parameters<typeof WikiTab>[0]>) {
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <WikiTab
        entries={ENTRIES}
        kbId="kb-1"
        onDeleteEntry={rs.fn()}
        onOpenCard={rs.fn()}
        onOpenEntry={rs.fn()}
        {...props}
      />
    </I18nContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("WikiTab", () => {
  it("renders the unified search box above the two section headers", () => {
    setupMocks();
    renderTab();
    expect(screen.getByPlaceholderText("搜索百科条目与卡片…")).toBeTruthy();
    expect(screen.getByTestId("wiki-entries-toggle").textContent).toContain(
      "生成条目",
    );
    expect(screen.getByTestId("manual-cards-toggle").textContent).toContain(
      "我的条目",
    );
  });

  it("lays the two sections out as a fixed-height split canvas that does not scroll itself (2026-09-03)", () => {
    setupMocks();
    renderTab();
    const canvas = screen.getByTestId("wiki-split-canvas");
    // 外层不再整体滚动（overflow-hidden + flex-col），滚动下放到每个抽屉卡内
    expect(canvas.className).toContain("overflow-hidden");
    expect(canvas.className).toContain("flex-col");
    expect(canvas.className).not.toContain("overflow-y-auto");
  });

  it("filters both sections with one query (cards force-expand to show matches)", () => {
    setupMocks();
    renderTab();
    // 初始：两区都展开（2026-09-04：我的条目不再默认收起）
    expect(screen.getByText("发布禁令")).toBeTruthy();
    expect(screen.getByText("DeerFlow")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("搜索百科条目与卡片…"), {
      target: { value: "发布" },
    });
    // AI 区无匹配 → no-match 文案；卡片区强制展开并命中
    expect(screen.queryByText("DeerFlow")).toBeNull();
    expect(screen.getByText("没有匹配的条目")).toBeTruthy();
    expect(screen.getByText("发布禁令")).toBeTruthy();
  });

  it("restores both lists via the clear button", () => {
    setupMocks();
    renderTab();
    fireEvent.change(screen.getByPlaceholderText("搜索百科条目与卡片…"), {
      target: { value: "网关" },
    });
    expect(screen.queryByText("DeerFlow")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
    expect(screen.getByText("DeerFlow")).toBeTruthy();
    expect(screen.getByText("Gateway")).toBeTruthy();
  });
});

// ── 百科 tab 内造题/维护入口（2026-08-30）──────────────────────
// 定案（用户拍板）：更新百科/重建百科本是百科功能却只在全局库菜单里；
// 在百科 tab 搜索框后加 ⋯ 承接，全局与 tab 内双入口。
describe("WikiTab 百科操作菜单", () => {
  it("搜索框后的 ⋯ 承接更新百科与重建百科，同栏高（h-7）", async () => {
    setupMocks();
    const onGenerateWiki = rs.fn();
    renderTab({ onGenerateWiki });
    const trigger = screen.getByRole("button", { name: "百科操作" });
    expect(trigger.className).toContain("size-7");

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.click(await screen.findByText("更新百科"));
    expect(onGenerateWiki).toHaveBeenCalledWith("incremental");

    // 重建项带图标（与全局库菜单一致，不能裸文字）
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const rebuildItem = (await screen.findByText("重建百科")).closest(
      "[role='menuitem']",
    )!;
    expect(rebuildItem.querySelector("svg")).toBeTruthy();
    fireEvent.click(rebuildItem);
    expect(await screen.findByText("全部重建百科？")).toBeTruthy();
    fireEvent.click(screen.getByText("取消"));
    expect(onGenerateWiki).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.click(await screen.findByText("重建百科"));
    fireEvent.click(await screen.findByText("确认重建"));
    expect(onGenerateWiki).toHaveBeenCalledWith("full");
  });

  it("更新中两项均禁用（与全局库菜单同规则）", async () => {
    setupMocks();
    const onGenerateWiki = rs.fn();
    renderTab({ onGenerateWiki, updating: true });
    fireEvent.keyDown(screen.getByRole("button", { name: "百科操作" }), {
      key: "ArrowDown",
    });
    // 头行更新中徽章也含「更新中」文案（2026-09-02），故按 menuitem 角色精确定位菜单项。
    const updateItem = await screen.findByRole("menuitem", { name: "更新中" });
    const rebuildItem = (await screen.findByText("重建百科")).closest(
      "[role='menuitem']",
    );
    expect(updateItem?.getAttribute("aria-disabled")).toBe("true");
    expect(rebuildItem?.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(updateItem);
    expect(onGenerateWiki).not.toHaveBeenCalled();
  });

  it("⋯ 菜单提供「新建卡片」全局入口，点击弹出创建框（2026-09-02）", async () => {
    setupMocks();
    renderTab();
    fireEvent.keyDown(screen.getByRole("button", { name: "百科操作" }), {
      key: "ArrowDown",
    });
    // 用 menuitem 角色定位 ⋯ 菜单项（卡片区头部「新建卡片」按钮已移除，⋯ 菜单为唯一入口）。
    const newCardItem = await screen.findByRole("menuitem", {
      name: "新建卡片",
    });
    expect(newCardItem.querySelector("svg")).toBeTruthy();
    // 新建卡片不受 updating 影响，始终可用。
    expect(newCardItem.getAttribute("aria-disabled")).not.toBe("true");
    fireEvent.click(newCardItem);
    // runAfterMenuClose 延到菜单退场后递增信号 → ManualCardPanel 弹出创建框。
    expect(
      await screen.findByText("新建知识卡片", undefined, { timeout: 3000 }),
    ).toBeTruthy();
  });

  it("⋯ 菜单：新建卡片沉底、其上方为新建抽屉；点新建抽屉弹出抽屉创建框（2026-09-04）", async () => {
    setupMocks();
    renderTab();
    fireEvent.keyDown(screen.getByRole("button", { name: "百科操作" }), {
      key: "ArrowDown",
    });
    const newDrawerItem = await screen.findByRole("menuitem", {
      name: "新建抽屉",
    });
    expect(newDrawerItem.querySelector("svg")).toBeTruthy();
    // 顺序：维护动作在上，新建抽屉 → 新建卡片 沉底（新建卡片在最下面）。
    const labels = screen
      .getAllByRole("menuitem")
      .map((el) => el.textContent ?? "");
    expect(labels[labels.length - 1]).toContain("新建卡片");
    expect(labels[labels.length - 2]).toContain("新建抽屉");
    // 点新建抽屉 → runAfterMenuClose 递增 drawerCreateSignal → ManualCardPanel 弹抽屉创建框。
    fireEvent.click(newDrawerItem);
    expect(
      await screen.findByTestId("drawer-editor-name", undefined, {
        timeout: 3000,
      }),
    ).toBeTruthy();
  });
});
