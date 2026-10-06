/**
 * Manual-card panel interactions after the wiki tab redesign: the section
 * shares the tab's unified search box (title/summary/tags containment;
 * searching force-expands the collapsed section, while the list fetch is
 * gated on tab-activation so the count badge shows even when collapsed), and
 * rows carry the document-table model — checkbox multi-select + batch delete
 * (irreversibility copy) and a right-click context menu (open / edit /
 * include-toggle / 取消选择 / 删除所选; batch variant inside a
 * multi-selection). 批量操作栏已退役（2026-09-02）：批量动作全由右键菜单承接；
 * 卡片区头部「新建卡片」按钮已移除，⋯ 菜单为唯一入口。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

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

import { ManualCardPanel } from "@/components/workspace/knowledge/manual-card-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { cardDrawersKey } from "@/core/knowledge/card-drawers";
import {
  useCreateManualCard,
  useDeleteManualCard,
  useManualCard,
  useManualCards,
  useUpdateManualCard,
} from "@/core/knowledge/hooks";
import type { ManualCardsPage } from "@/core/knowledge/types";

const CARDS_PAGE: ManualCardsPage = {
  items: [
    {
      id: "card-1",
      title: "发布禁令",
      summary: "周五下午不发布",
      tags: ["ops"],
      include_in_wiki_search: true,
      created_at: "2026-08-15T10:00:00Z",
      updated_at: "2026-08-15T10:00:00Z",
    },
    {
      id: "card-2",
      title: "回滚流程",
      summary: "先切流量再回滚",
      tags: [],
      include_in_wiki_search: false,
      created_at: "2026-08-15T09:00:00Z",
      updated_at: "2026-08-15T09:00:00Z",
    },
  ],
  total: 2,
  offset: 0,
  limit: 50,
};

function setupMocks({ cardsPage = CARDS_PAGE } = {}) {
  const createCard = {
    mutateAsync: rs.fn().mockResolvedValue({}),
    isPending: false,
  };
  const updateCard = {
    mutateAsync: rs.fn().mockResolvedValue({}),
    isPending: false,
  };
  const deleteCard = {
    mutateAsync: rs.fn().mockResolvedValue(undefined),
    isPending: false,
  };
  rs.mocked(useManualCards).mockReturnValue({
    data: cardsPage,
    isLoading: false,
  } as never);
  rs.mocked(useManualCard).mockReturnValue({ data: null } as never);
  rs.mocked(useCreateManualCard).mockReturnValue(createCard as never);
  rs.mocked(useUpdateManualCard).mockReturnValue(updateCard as never);
  rs.mocked(useDeleteManualCard).mockReturnValue(deleteCard as never);
  return { createCard, updateCard, deleteCard };
}

function renderPanel(props?: Partial<Parameters<typeof ManualCardPanel>[0]>) {
  const onOpenCard = rs.fn();
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <ManualCardPanel kbId="kb-1" onOpenCard={onOpenCard} {...props} />
    </I18nContext.Provider>,
  );
  return { onOpenCard };
}

/** 我的条目 默认已展开（2026-09-04）；点头部为幂等无害，保留以沿用既有断言流程。 */
function renderExpanded(
  props?: Partial<Parameters<typeof ManualCardPanel>[0]>,
) {
  const utils = renderPanel(props);
  fireEvent.click(screen.getByTestId("manual-cards-toggle"));
  return utils;
}

afterEach(async () => {
  // happy-dom crashes when cleanup unmounts the tree while a Radix context
  // menu is still open or animating closed; always settle the menu first.
  if (document.querySelector('[role="menu"]')) {
    fireEvent.keyDown(document.body, { key: "Escape" });
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  cleanup();
  rs.clearAllMocks();
  window.localStorage.clear();
});

describe("ManualCardPanel search filtering", () => {
  it("force-expands the collapsed section while searching; fetch gated on tab-active（2026-09-02）", () => {
    setupMocks();
    // 搜索发生在 tab 激活时（active=true）→ 取数已放开（门控从「分区展开/搜索」上移到
    // 「tab 激活」）；搜索另触发强制展开（渲染门控），故收起的区也能被搜到。
    renderPanel({ query: "发布", active: true });
    expect(rs.mocked(useManualCards).mock.calls[0]?.slice(0, 2)).toEqual([
      "kb-1",
      true,
    ]);
    expect(screen.getByText("发布禁令")).toBeTruthy();
    expect(screen.queryByText("回滚流程")).toBeNull();
  });

  it("matches against tags and summary too", () => {
    setupMocks();
    renderPanel({ query: "ops" });
    expect(screen.getByText("发布禁令")).toBeTruthy();
    expect(screen.queryByText("回滚流程")).toBeNull();
  });

  it("shows the no-match empty state when nothing matches", () => {
    setupMocks();
    renderPanel({ query: "不存在的词" });
    expect(screen.getByText("没有匹配的卡片")).toBeTruthy();
    expect(screen.queryByText("发布禁令")).toBeNull();
  });
});

describe("ManualCardPanel selection", () => {
  it("selects rows via checkboxes; the batch bar is retired（2026-09-02）", () => {
    setupMocks();
    renderExpanded();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 发布禁令" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 回滚流程" }),
    );
    expect(screen.queryByTestId("manual-cards-batch-bar")).toBeNull();
    expect(
      screen
        .getByRole("checkbox", { name: "选择卡片: 发布禁令" })
        .getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("selects all rows via the header checkbox", () => {
    setupMocks();
    renderExpanded();
    fireEvent.click(screen.getByRole("checkbox", { name: "全选" }));
    for (const title of ["发布禁令", "回滚流程"]) {
      expect(
        screen
          .getByRole("checkbox", { name: `选择卡片: ${title}` })
          .getAttribute("aria-checked"),
      ).toBe("true");
    }
  });

  it("batch-deletes the selected cards via the context menu after confirm (irreversibility copy)", async () => {
    const { deleteCard } = setupMocks();
    renderExpanded();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 发布禁令" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 回滚流程" }),
    );
    // 批量栏退役后，批量删除唯一入口是右键菜单。
    fireEvent.contextMenu(screen.getByTestId("manual-card-row-card-1"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除所选" }));
    expect(
      await screen.findByText("删除 2 张知识卡片？", undefined, {
        timeout: 3000,
      }),
    ).toBeTruthy();
    expect(screen.getByText(/删除后不可恢复/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(
      () => expect(deleteCard.mutateAsync).toHaveBeenCalledTimes(2),
      { timeout: 2000 },
    );
    expect(deleteCard.mutateAsync).toHaveBeenCalledWith("card-1");
    expect(deleteCard.mutateAsync).toHaveBeenCalledWith("card-2");
  });

  it("batch-moves the selected cards into a drawer via the context menu (req3)", async () => {
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "d1", name: "运维手册", icon: "folder", color: "emerald" },
        ],
        membership: {},
      }),
    );
    setupMocks();
    renderExpanded();
    // 首页(未分组)选中两张卡 → 右键 → 多选菜单现在有「移动到抽屉」（此前只有取消选择/删除所选）。
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 发布禁令" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 回滚流程" }),
    );
    fireEvent.contextMenu(screen.getByTestId("manual-card-row-card-1"));
    const moveTrigger = await screen.findByRole("menuitem", {
      name: "移动到抽屉",
    });
    fireEvent.pointerEnter(moveTrigger);
    fireEvent.pointerMove(moveTrigger, { pointerType: "mouse" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "运维手册" }));
    // 两张卡一次性归入 d1（moveCards 单次 persist 写全部）。
    await waitFor(() => {
      const stored = JSON.parse(
        window.localStorage.getItem(cardDrawersKey("kb-1"))!,
      );
      expect(stored.membership["card-1"]).toBe("d1");
      expect(stored.membership["card-2"]).toBe("d1");
    });
  });
});

describe("ManualCardPanel context menu", () => {
  // NOTE: under happy-dom a Radix context menu can only complete ONE
  // open/close cycle per mounted tree — each test below performs exactly one
  // cycle and fully settles before cleanup.
  const settleMenu = async () => {
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  };

  it("offers single-row actions on an unselected row", async () => {
    setupMocks();
    renderExpanded();
    fireEvent.contextMenu(screen.getByTestId("manual-card-row-card-1"));
    expect(
      await screen.findByRole("menuitem", { name: "打开详情" }),
    ).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "编辑卡片" })).toBeTruthy();
    // card-1 已开启混入搜索 → 菜单项为关闭
    expect(screen.getByRole("menuitem", { name: "关闭混入搜索" })).toBeTruthy();
    // 措辞对齐（2026-09-02）：右键即选中，单选菜单用「删除所选」；退出选择态两态对称。
    expect(screen.getByRole("menuitem", { name: "删除所选" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "取消选择" })).toBeTruthy();
    await settleMenu();
  });

  it("toggles 混入搜索 from the menu for an opted-out card", async () => {
    const { updateCard } = setupMocks();
    renderExpanded();
    fireEvent.contextMenu(screen.getByTestId("manual-card-row-card-2"));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "开启混入搜索" }),
    );
    await waitFor(() =>
      expect(updateCard.mutateAsync).toHaveBeenCalledWith({
        cardId: "card-2",
        body: { include_in_wiki_search: true },
      }),
    );
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  });

  it("offers batch actions when right-clicking inside a multi-selection", async () => {
    setupMocks();
    renderExpanded();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 发布禁令" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "选择卡片: 回滚流程" }),
    );
    fireEvent.contextMenu(screen.getByTestId("manual-card-row-card-1"));
    expect(
      await screen.findByRole("menuitem", { name: "删除所选" }),
    ).toBeTruthy();
    // 批量栏退役后，计数反馈唯一载体是菜单标签。
    expect(screen.getAllByText("已选 2 项").length).toBeGreaterThan(0);
    await settleMenu();
  });

  it("drawer right-click menu: 新建卡片 与 编辑抽屉 间无分割线（req4，仅删除前留隔离线）", async () => {
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "d1", name: "运维手册", icon: "folder", color: "emerald" },
        ],
        membership: {},
      }),
    );
    setupMocks();
    renderExpanded();
    fireEvent.contextMenu(screen.getByTestId("drawer-tab-d1"));
    expect(
      await screen.findByRole("menuitem", { name: "新建卡片" }),
    ).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "编辑抽屉" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "删除抽屉" })).toBeTruthy();
    // 分割线只剩「删除」前那一条（新建卡片↔编辑抽屉之间不再分隔）。
    expect(screen.getAllByRole("separator")).toHaveLength(1);
    await settleMenu();
  });
});
