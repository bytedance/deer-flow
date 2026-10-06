/**
 * Manual knowledge cards panel (Phase-3 Batch-1 P6, spec §8): collapsible
 * section under the wiki tab — card list (title + summary + 混入搜索 badge),
 * create/edit dialog with validation, per-row include toggle, delete behind a
 * confirm dialog. Manual cards never auto-update and stay isolated from the
 * AI-generated wiki entries.
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
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
import type { ManualCardDetail, ManualCardsPage } from "@/core/knowledge/types";

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

const CARD_DETAIL: ManualCardDetail = {
  id: "card-1",
  kb_id: "kb-1",
  owner_id: "user-1",
  title: "发布禁令",
  content: "周五下午不发布，紧急修复走审批",
  tags: ["ops"],
  include_in_wiki_search: true,
  created_at: "2026-08-15T10:00:00Z",
  updated_at: "2026-08-15T10:00:00Z",
};

function setupMocks({
  cardsPage = CARDS_PAGE,
  isLoading = false,
  cardDetail = null as ManualCardDetail | null,
} = {}) {
  const createCard = {
    mutateAsync: rs.fn().mockResolvedValue({ id: "new-card-1" }),
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
    isLoading,
  } as never);
  rs.mocked(useManualCard).mockReturnValue({ data: cardDetail } as never);
  rs.mocked(useCreateManualCard).mockReturnValue(createCard as never);
  rs.mocked(useUpdateManualCard).mockReturnValue(updateCard as never);
  rs.mocked(useDeleteManualCard).mockReturnValue(deleteCard as never);
  return { createCard, updateCard, deleteCard };
}

function renderPanel(props?: {
  onOpenCard?: (cardId: string) => void;
  active?: boolean;
}) {
  return render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <ManualCardPanel kbId="kb-1" {...props} />
    </I18nContext.Provider>,
  );
}

/** Collapsed by default — expand through the section header. */
function renderExpanded(props?: { onOpenCard?: (cardId: string) => void }) {
  const utils = renderPanel(props);
  fireEvent.click(screen.getByTestId("manual-cards-toggle"));
  return utils;
}

/** 头部「新建卡片」按钮已移除（2026-09-02，⋯ 菜单为唯一入口）——创建框改由
 *  createSignal 触发：先挂载 createSignal=0，再 rerender 到 1，派生状态监听增量
 *  弹框（并自动展开卡片区）。 */
function renderWithCreateOpen() {
  const utils = render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <ManualCardPanel kbId="kb-1" createSignal={0} />
    </I18nContext.Provider>,
  );
  utils.rerender(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <ManualCardPanel kbId="kb-1" createSignal={1} />
    </I18nContext.Provider>,
  );
  return utils;
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
  window.localStorage.clear();
});

describe("ManualCardPanel", () => {
  it("is expanded by default and collapses via the chevron（2026-09-04：与生成条目一致，两区都展开）", () => {
    setupMocks();
    renderPanel();

    // 默认展开：切进百科 tab 我的条目即展开，卡片行直接可见。
    expect(screen.getByText("我的条目")).toBeTruthy();
    expect(screen.getByText("发布禁令")).toBeTruthy();
    expect(screen.getByText("回滚流程")).toBeTruthy();

    // 箭头收起 → 列表行隐藏。
    fireEvent.click(screen.getByTestId("manual-cards-collapse"));
    expect(screen.queryByText("发布禁令")).toBeNull();
  });

  it("我的条目 展开为 flex-1 内滚面板、箭头收起为 shrink-0 细条，两态都不 mt-auto 钉底（2026-09-04）", () => {
    setupMocks();
    renderPanel();
    // 默认展开：flex-1 吃一份额定高度，列表卡内 overflow-y-auto 内滚，不 mt-auto。
    const expanded = screen.getByTestId("manual-cards-section");
    expect(expanded.className).toContain("flex-1");
    expect(expanded.className).not.toContain("mt-auto");
    expect(
      screen
        .getByTestId("manual-card-list")
        .closest('[data-slot="scroll-area"]'),
    ).toBeTruthy();
    // 箭头收起：shrink-0 细条，仍不 mt-auto（此前钉底导致生成条目收起后本区不上移）。
    fireEvent.click(screen.getByTestId("manual-cards-collapse"));
    const collapsed = screen.getByTestId("manual-cards-section");
    expect(collapsed.className).toContain("shrink-0");
    expect(collapsed.className).not.toContain("mt-auto");
  });

  it("取数门控为 tab 激活而非分区展开：收起态即拉取，计数徽章可见（2026-09-02）", () => {
    setupMocks();
    // active=true：取数触发（与 AI 条目 useWikiEntries 同节奏），与展开无关。
    renderPanel({ active: true });
    expect(useManualCards).toHaveBeenCalledWith("kb-1", true);
    // 默认展开；手动箭头收起后：列表行不渲染，但计数徽章「2」仍在头行可见（门控是 active）。
    fireEvent.click(screen.getByTestId("manual-cards-collapse"));
    expect(screen.queryByText("发布禁令")).toBeNull();
    expect(screen.getByTestId("manual-cards-toggle").textContent).toContain(
      "2",
    );
  });

  it("tab 未激活时不取数（keep-alive 懒门控）", () => {
    setupMocks();
    renderPanel(); // active 默认 false
    expect(useManualCards).toHaveBeenCalledWith("kb-1", false);
  });

  it("reveals the row ⋯ action on hover like the AI rows (no permanent right gutter)", () => {
    setupMocks();
    renderExpanded();

    // 行通栏：不再为常驻操作区预留 pr-28
    const row = screen.getByTestId("manual-card-row-card-1");
    expect(row.className).not.toContain("pr-28");
    // 行尾 ⋯（2026-09-03）：取代 hover 浮现的 Switch/编辑/删除，opacity 门控淡入
    const more = screen.getAllByRole("button", { name: "更多操作" })[0]!;
    const moreWrap = more.closest("div.transition-opacity");
    expect(moreWrap?.className).toContain("opacity-0");
    expect(moreWrap?.className).toContain("group-hover:opacity-100");
  });

  it("shows the 混入搜索 badge only on opted-in cards", () => {
    setupMocks();
    renderExpanded();

    // card-1 opted-in → 徐章；card-2 not → 无。两行合计恰好一枚。
    expect(screen.getAllByText("混入搜索")).toHaveLength(1);
  });

  it("keeps the 混入搜索 badge at row-line height (h-5 py-0) so toggling never shifts row height", () => {
    setupMocks();
    renderExpanded();

    // Badge 默认 22px（py-0.5 + text-xs 行高 + border），比标题行 20px 高——
    // 开关切换徽章动态出现/消失会把行撑高 2px。锁 h-5 py-0 与行高一致。
    const badge = screen.getByText("混入搜索");
    expect(badge.className).toContain("h-5");
    expect(badge.className).toContain("py-0");
  });

  it("renders the empty state when expanded with no cards", () => {
    setupMocks({ cardsPage: { items: [], total: 0, offset: 0, limit: 50 } });
    renderExpanded();

    expect(screen.getByText(/记录属于你的知识/)).toBeTruthy();
  });

  it("creates a card from the dialog with validation", async () => {
    const { createCard } = setupMocks();
    renderWithCreateOpen();

    const saveButton = screen.getByRole("button", { name: "保存" });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("标题"), {
      target: { value: "  新卡片  " },
    });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true); // content still blank
    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "正文内容" },
    });
    expect((saveButton as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(saveButton);
    await waitFor(() => {
      expect(createCard.mutateAsync).toHaveBeenCalledWith({
        title: "新卡片",
        content: "正文内容",
        tags: [],
        include_in_wiki_search: false,
      });
    });
  });

  it("keeps the editor textarea constrained to the dialog width (min-w-0 chain) so long lines soft-wrap", async () => {
    setupMocks();
    renderWithCreateOpen();

    // field-sizing-content 的 textarea 把「内容不换行宽度」作为 min-content 贡献
    // 沿 grid/flex item 链向上传递撑宽对话框（修复前：输入框超出编辑界面）。
    // 链上每个 flex 容器与 textarea 自身都要 min-w-0。
    const contentField = await screen.findByLabelText("内容");
    let node: HTMLElement | null = contentField;
    while (node && node.getAttribute("data-slot") !== "dialog-content") {
      if (node.tagName === "TEXTAREA" || node.className.includes("flex")) {
        expect(node.className).toContain("min-w-0");
      }
      node = node.parentElement;
    }
  });

  it("toggles a row's include via the ⋯ menu", async () => {
    const { updateCard } = setupMocks();
    renderExpanded();

    // 开关移进行尾 ⋯ 菜单（2026-09-03）：card-2 未开启 → 菜单项「开启混入搜索」
    fireEvent.keyDown(screen.getAllByRole("button", { name: "更多操作" })[1]!, {
      key: "ArrowDown",
    });
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "开启混入搜索" }),
    );

    await waitFor(() => {
      expect(updateCard.mutateAsync).toHaveBeenCalledWith({
        cardId: "card-2",
        body: { include_in_wiki_search: true },
      });
    });
  });

  it("opens the editor prefilled for an existing card and saves changes", async () => {
    const { updateCard } = setupMocks({ cardDetail: CARD_DETAIL });
    renderExpanded();

    // 编辑移进行尾 ⋯ 菜单（2026-09-03）
    fireEvent.keyDown(screen.getAllByRole("button", { name: "更多操作" })[0]!, {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "编辑卡片" }));
    const contentField = await screen.findByLabelText("内容");
    expect((contentField as HTMLTextAreaElement).value).toBe(
      "周五下午不发布，紧急修复走审批",
    );
    const titleField = await screen.findByLabelText("标题");
    expect((titleField as HTMLInputElement).value).toBe("发布禁令");

    fireEvent.change(contentField, { target: { value: "周五全天不发布" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(updateCard.mutateAsync).toHaveBeenCalledWith({
        cardId: "card-1",
        body: {
          title: "发布禁令",
          content: "周五全天不发布",
          tags: ["ops"],
          include_in_wiki_search: true,
        },
      });
    });
  });

  it("deletes a card behind a confirm dialog", async () => {
    const { deleteCard } = setupMocks();
    renderExpanded();

    // 删除移进行尾 ⋯ 菜单（2026-09-03）
    fireEvent.keyDown(screen.getAllByRole("button", { name: "更多操作" })[0]!, {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除卡片" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));

    await waitFor(() => {
      expect(deleteCard.mutateAsync).toHaveBeenCalledWith("card-1");
    });
  });

  it("opens the card detail drawer on row click, mirroring wiki entries (P6 fix)", () => {
    setupMocks();
    const onOpenCard = rs.fn();
    renderExpanded({ onOpenCard });

    fireEvent.click(screen.getByTestId("manual-card-row-card-1"));
    expect(onOpenCard).toHaveBeenCalledWith("card-1");
    fireEvent.click(screen.getByTestId("manual-card-row-card-2"));
    expect(onOpenCard).toHaveBeenCalledWith("card-2");
  });

  it("row ⋯ actions never trigger the drawer", async () => {
    setupMocks();
    const onOpenCard = rs.fn();
    renderExpanded({ onOpenCard });

    // 行尾 ⋯ 菜单在 portal 中渲染、触发器带 stopPropagation——菜单动作不会冒泡到行点击。
    fireEvent.keyDown(screen.getAllByRole("button", { name: "更多操作" })[1]!, {
      key: "ArrowDown",
    });
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "开启混入搜索" }),
    );

    expect(onOpenCard).not.toHaveBeenCalled();
  });
});

/**
 * 用户自建抽屉（2026-09-04，水平浏览器标签模型）：「我的条目」头部下方一条水平
 * 标签条——常驻「我的条目」首页标签 + 用户抽屉标签（可关）+ 尾部 [+]。预置抽屉
 * d1（card-1 归入）→首页标签只显示未分组 card-2、点 d1 标签只看 card-1、[+] 开弹窗、
 * 右键「移动到抽屉」改 membership、关标签(×)删抽屉后 card-1 回首页。
 */
describe("ManualCardPanel — 用户自建抽屉（水平标签条）", () => {
  beforeEach(() => {
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "d1", name: "运维手册", icon: "folder", color: "emerald" },
        ],
        membership: { "card-1": "d1" },
      }),
    );
  });

  /** 标签主体是个按钮（可及名 = 标签名）；× 关闭按钮另有 testid。 */
  function clickTab(name: string) {
    fireEvent.click(screen.getByRole("button", { name }));
  }

  it("头部与生成条目一致（标题+计数），计数后跟用户抽屉 strip；无独立首页签，默认只显示未分组 card-2", () => {
    setupMocks();
    renderExpanded();

    // 头部与生成条目一致：标题「我的条目」+ 计数胶囊始终在 toggle 内可见。
    expect(screen.getByTestId("manual-cards-toggle").textContent).toContain(
      "我的条目",
    );
    expect(screen.getByTestId("manual-cards-toggle").textContent).toContain(
      "2",
    );
    // 计数后面是用户抽屉 strip（只显示未收起的 d1）；右侧固定 -> 下拉 + 全选。
    expect(screen.getByTestId("drawer-tab-strip")).toBeTruthy();
    expect(screen.getByTestId("drawer-tab-d1")).toBeTruthy();
    expect(screen.getByTestId("manual-cards-drawer-overflow")).toBeTruthy();
    expect(screen.queryByTestId("drawer-tab-home")).toBeNull();
    // 默认无抽屉激活 → 首页(未分组)只显示 card-2。
    expect(
      screen.getByTestId("drawer-tab-d1").getAttribute("data-active"),
    ).toBe("false");
    expect(screen.getByTestId("manual-card-row-card-2")).toBeTruthy();
    expect(screen.queryByTestId("manual-card-row-card-1")).toBeNull();
  });

  it("点抽屉签切到该抽屉只看 card-1；再点同一签取消选择回首页只看 card-2", () => {
    setupMocks();
    renderExpanded();

    clickTab("运维手册");
    expect(
      screen.getByTestId("drawer-tab-d1").getAttribute("data-active"),
    ).toBe("true");
    expect(screen.getByTestId("manual-card-row-card-1")).toBeTruthy();
    expect(screen.queryByTestId("manual-card-row-card-2")).toBeNull();

    // 再点当前激活的抽屉 → 取消选择 → 回首页(未分组)。
    clickTab("运维手册");
    expect(
      screen.getByTestId("drawer-tab-d1").getAttribute("data-active"),
    ).toBe("false");
    expect(screen.getByTestId("manual-card-row-card-2")).toBeTruthy();
    expect(screen.queryByTestId("manual-card-row-card-1")).toBeNull();
  });

  it("箭头负责展开/收起；点「我的条目」标题切回首页而非收起", () => {
    setupMocks();
    renderExpanded();

    // 选中抽屉 d1
    clickTab("运维手册");
    expect(
      screen.getByTestId("drawer-tab-d1").getAttribute("data-active"),
    ).toBe("true");

    // 点「我的条目」标题 → 切回首页（d1 取消激活），分区仍展开（未收起）。
    fireEvent.click(screen.getByTestId("manual-cards-toggle"));
    expect(
      screen.getByTestId("drawer-tab-d1").getAttribute("data-active"),
    ).toBe("false");
    expect(screen.getByTestId("manual-card-row-card-2")).toBeTruthy();
    expect(screen.getByTestId("drawer-tab-strip")).toBeTruthy();

    // 箭头 → 收起（strip 消失）。
    fireEvent.click(screen.getByTestId("manual-cards-collapse"));
    expect(screen.queryByTestId("drawer-tab-strip")).toBeNull();
  });

  it("-> 下拉底部「新建抽屉」开创建抽屉弹窗（行尾 [+] 已恢复，下拉底部保留作次入口）", async () => {
    setupMocks();
    renderExpanded();

    // DropdownMenu 靠 keydown 打开（happy-dom 里 click 不触发 Radix 的 pointerdown 开启）。
    fireEvent.keyDown(screen.getByTestId("manual-cards-drawer-overflow"), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "新建抽屉" }));
    expect(await screen.findByTestId("drawer-editor-name")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "新建抽屉" })).toBeTruthy();
  });

  it("右键「移动到抽屉 ▸ 运维手册」把 card-2 归入 d1，离开首页标签", async () => {
    setupMocks();
    renderExpanded();

    // 首页标签下右键未分组的 card-2 → 单选态右键菜单 → 「移动到抽屉」子菜单。
    fireEvent.contextMenu(screen.getByTestId("manual-card-row-card-2"));
    const moveTrigger = await screen.findByRole("menuitem", {
      name: "移动到抽屉",
    });
    fireEvent.pointerEnter(moveTrigger);
    fireEvent.pointerMove(moveTrigger, { pointerType: "mouse" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "运维手册" }));

    await waitFor(() => {
      const stored = JSON.parse(
        window.localStorage.getItem(cardDrawersKey("kb-1"))!,
      );
      expect(stored.membership["card-2"]).toBe("d1");
    });
    // card-2 已归入 d1 → 离开首页标签（首页此时无未分组卡片）。
    await waitFor(() => {
      expect(screen.queryByTestId("manual-card-row-card-2")).toBeNull();
    });
  });

  it("× 收起抽屉：标签从行内消失但抽屉保留（hidden）、membership 不动；-> 下拉点它可恢复", async () => {
    setupMocks();
    renderExpanded();

    fireEvent.click(screen.getByTestId("drawer-tab-d1-close"));

    // 收起：标签从行内消失；但抽屉未删除——hidden=true、card-1 归属保留。
    expect(screen.queryByTestId("drawer-tab-d1")).toBeNull();
    const stored = JSON.parse(
      window.localStorage.getItem(cardDrawersKey("kb-1"))!,
    );
    expect(stored.drawers).toHaveLength(1);
    expect(stored.drawers[0].hidden).toBe(true);
    expect(stored.membership["card-1"]).toBe("d1");

    // -> 下拉里点它 → 取消收起、标签恢复、跳转过去（只看 card-1）。
    fireEvent.keyDown(screen.getByTestId("manual-cards-drawer-overflow"), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "运维手册" }));
    expect(await screen.findByTestId("drawer-tab-d1")).toBeTruthy();
    expect(screen.getByTestId("manual-card-row-card-1")).toBeTruthy();
    expect(screen.queryByTestId("manual-card-row-card-2")).toBeNull();
  });

  it("右键抽屉条目「新建卡片」→ 开创建框；保存后新卡归入该抽屉（membership 写入）", async () => {
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "d1", name: "运维手册", icon: "folder", color: "emerald" },
        ],
        membership: {},
      }),
    );
    const { createCard } = setupMocks();
    renderExpanded();

    // 右键抽屉 d1 条目 → 菜单含「新建卡片」（此前抽屉右键只有编辑/删除）。
    fireEvent.contextMenu(screen.getByTestId("drawer-tab-d1"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "新建卡片" }));

    // 创建框异步开（runAfterMenuClose）；填标题+内容后保存。
    fireEvent.change(await screen.findByLabelText("标题"), {
      target: { value: "新卡片" },
    });
    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "正文内容" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(createCard.mutateAsync).toHaveBeenCalled());
    // 新卡归入当前展示的抽屉 d1（handleSave 按 activeDrawerId 调 moveCard）。
    await waitFor(() => {
      const stored = JSON.parse(
        window.localStorage.getItem(cardDrawersKey("kb-1"))!,
      );
      expect(stored.membership["new-card-1"]).toBe("d1");
    });
  });

  it("-> 下拉点击抽屉：取消收起并移到最前（排在其他抽屉之前，紧跟「我的条目」）", async () => {
    // 两个抽屉 [d1 运维手册, d2 发布规范]，各含一张卡。
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "d1", name: "运维手册", icon: "folder", color: "emerald" },
          { id: "d2", name: "发布规范", icon: "star", color: "blue" },
        ],
        membership: { "card-1": "d1", "card-2": "d2" },
      }),
    );
    setupMocks();
    renderExpanded();

    // 收起第二个抽屉 d2 → 行内只剩 d1。
    fireEvent.click(screen.getByTestId("drawer-tab-d2-close"));
    expect(screen.queryByTestId("drawer-tab-d2")).toBeNull();

    // -> 下拉点 d2 → 取消收起并移到最前：strip 顺序变为 [d2, d1]，且跳转到 d2。
    fireEvent.keyDown(screen.getByTestId("manual-cards-drawer-overflow"), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "发布规范" }));

    const text = screen.getByTestId("drawer-tab-strip").textContent ?? "";
    // d2「发布规范」已移到 d1「运维手册」之前。
    expect(text.indexOf("发布规范")).toBeGreaterThanOrEqual(0);
    expect(text.indexOf("发布规范")).toBeLessThan(text.indexOf("运维手册"));
    // 跳转到 d2 → 只看 card-2。
    expect(await screen.findByTestId("manual-card-row-card-2")).toBeTruthy();
    expect(screen.queryByTestId("manual-card-row-card-1")).toBeNull();
  });

  it("全选框在展示任意抽屉时都显示（req2：不再只在首页出现，空抽屉也在）", () => {
    // d1 有 card-1；d2 空。选中空抽屉 d2 时本区仍有卡片 → 全选框应显示。
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "d1", name: "运维手册", icon: "folder", color: "emerald" },
          { id: "d2", name: "空抽屉", icon: "star", color: "blue" },
        ],
        membership: { "card-1": "d1" },
      }),
    );
    setupMocks();
    renderExpanded();

    // 选中空抽屉 d2 → 无卡片行，但全选框仍在（cards.length>0，不再要求当前视图非空）。
    clickTab("空抽屉");
    expect(screen.queryByTestId("manual-card-row-card-1")).toBeNull();
    expect(screen.getByRole("checkbox")).toBeTruthy();
  });

  it("-> 下拉按钮默认隐藏（悬停头部才显现），菜单打开时保持可见", async () => {
    setupMocks();
    renderExpanded();
    const overflow = screen.getByTestId("manual-cards-drawer-overflow");
    // 未打开：opacity-0 占位隐藏 + group-hover/header 显现钩子（req2b）。
    expect(overflow.className).toContain("opacity-0");
    expect(overflow.className).toContain("group-hover/header:opacity-100");
    // 打开菜单：受控 drawerMenuOpen → 去掉 opacity-0，强制可见（脱离 group-hover 也在）。
    fireEvent.keyDown(overflow, { key: "ArrowDown" });
    await screen.findByRole("menuitem", { name: "新建抽屉" });
    expect(overflow.className).not.toContain("opacity-0");
  });

  it("内容区空白右键 →「新建卡片」开创建框，保存后归入当前抽屉（req2）", async () => {
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "d1", name: "运维手册", icon: "folder", color: "emerald" },
        ],
        membership: {},
      }),
    );
    const { createCard } = setupMocks();
    renderExpanded();
    // 切到空抽屉 d1 → 内容区是空态；右键内容容器（非卡片行）→ 外层菜单「新建卡片」。
    clickTab("运维手册");
    fireEvent.contextMenu(screen.getByTestId("manual-cards-content"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "新建卡片" }));
    // 创建框异步开（runAfterMenuClose）；填标题+内容保存。
    fireEvent.change(await screen.findByLabelText("标题"), {
      target: { value: "新卡片" },
    });
    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "正文内容" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(createCard.mutateAsync).toHaveBeenCalled());
    // 新卡归入当前展示的抽屉 d1（openCreateFor(activeDrawerId)+handleSave moveCard）。
    await waitFor(() => {
      const stored = JSON.parse(
        window.localStorage.getItem(cardDrawersKey("kb-1"))!,
      );
      expect(stored.membership["new-card-1"]).toBe("d1");
    });
  });

  it("抽屉行布局（req1 回归修正）：strip 内容宽不 flex-1、[+] 紧跟、flex-1 垫片把右侧控件顶到栏最右", () => {
    setupMocks();
    renderExpanded();
    // strip 不再 flex-1（内容宽 + min-w-0 可收缩裁切）——这样行尾 [+] 才能紧跟最后一个标签；
    const strip = screen.getByTestId("drawer-tab-strip");
    expect(strip.className).not.toContain("flex-1");
    expect(strip.className).toContain("overflow-hidden");
    // 右侧控件改由 flex-1 垫片顶到栏最右并随栏宽跟随（垫片吃掉多余横向空间；溢出时 basis:0 收缩为 0，[+] 贴到控件左侧）。
    expect(screen.getByTestId("drawer-strip-spacer").className).toContain(
      "flex-1",
    );
    // [+] shrink-0：标签溢出、strip 收缩裁切时它不被裁。
    expect(screen.getByTestId("manual-cards-drawer-add").className).toContain(
      "shrink-0",
    );
  });

  it("行尾 [+] 打开新建抽屉弹窗（req1）", async () => {
    setupMocks();
    renderExpanded();
    fireEvent.click(screen.getByTestId("manual-cards-drawer-add"));
    expect(await screen.findByTestId("drawer-editor-name")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "新建抽屉" })).toBeTruthy();
  });

  it("抽屉标签 w-28 容 ≥4 汉字、硬截断不带省略号、pr-1 贴 × 边界（req2）", () => {
    setupMocks();
    renderExpanded();
    const tab = screen.getByTestId("drawer-tab-d1");
    // w-28（曾 w-24 只容 ~2 字）：容纳图标 + ≥4 个汉字 + × 收起按钮。
    expect(tab.className).toContain("w-28");
    // 硬截断：overflow-hidden + whitespace-nowrap（text-overflow 默认 clip），不再 truncate/省略号。
    expect(
      tab.querySelector("span.overflow-hidden.whitespace-nowrap"),
    ).toBeTruthy();
    expect(tab.querySelector("span.truncate")).toBeNull();
    // 标签按钮右内边距收到 pr-1，让文字截断点贴近 × 边界。
    expect(tab.querySelector("button")?.className).toContain("pr-1");
  });

  it("抽屉行空白垫片右键 →「新建抽屉」开创建框（req3）", async () => {
    setupMocks();
    renderExpanded();
    fireEvent.contextMenu(screen.getByTestId("drawer-strip-spacer"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "新建抽屉" }));
    expect(await screen.findByTestId("drawer-editor-name")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "新建抽屉" })).toBeTruthy();
  });
});
