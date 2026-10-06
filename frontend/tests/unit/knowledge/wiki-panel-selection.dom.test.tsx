/**
 * Wiki panel split-section interactions (wiki tab redesign): the AI entries
 * section is collapsible (default expanded, auto-expands when a unified
 * search query matches), filters client-side by the shared query, and carries
 * the document-table interaction model — checkbox multi-select + batch delete
 * through the shared confirm dialog, and a Radix context menu (open / edit /
 * 取消选择 / 删除所选; batch variant inside a multi-selection). 批量操作栏
 * 已退役（2026-09-02）：批量动作全由右键菜单承接。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WikiPanel } from "@/components/workspace/knowledge/wiki-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { WikiEntrySummary } from "@/core/knowledge/types";

function entry(partial: Partial<WikiEntrySummary>): WikiEntrySummary {
  return {
    id: "entry-1",
    title: "DeerFlow",
    summary: "LangGraph 超级代理系统",
    status: "ready",
    updated_at: "2026-08-10T08:00:00Z",
    ...partial,
  };
}

const ENTRIES = [
  entry({ id: "a", title: "DeerFlow", summary: "超级代理系统" }),
  entry({ id: "b", title: "Gateway", summary: "网关负责统一鉴权与路由" }),
  entry({ id: "c", title: "沙箱", summary: "代码在隔离沙箱中执行" }),
];

function renderPanel(props?: Partial<Parameters<typeof WikiPanel>[0]>) {
  const handlers = {
    onOpenEntry: rs.fn(),
    onDeleteEntry: rs.fn(),
    onEditEntry: rs.fn(),
    onRegenerateEntries: rs.fn(),
  };
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <WikiPanel entries={ENTRIES} {...handlers} {...props} />
    </I18nContext.Provider>,
  );
  return handlers;
}

afterEach(async () => {
  // happy-dom crashes when cleanup unmounts the tree while a Radix context
  // menu is still open or animating closed; always settle the menu first.
  if (document.querySelector('[role="menu"]')) {
    fireEvent.keyDown(document.body, { key: "Escape" });
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  cleanup();
});

describe("WikiPanel section collapse", () => {
  it("is expanded by default and collapses via the section header", () => {
    renderPanel();
    expect(screen.getByText("DeerFlow")).toBeTruthy();

    fireEvent.click(screen.getByTestId("wiki-entries-toggle"));
    expect(screen.queryByText("DeerFlow")).toBeNull();

    fireEvent.click(screen.getByTestId("wiki-entries-toggle"));
    expect(screen.getByText("DeerFlow")).toBeTruthy();
  });

  it("auto-expands a collapsed section while the search query matches", () => {
    renderPanel({ query: "网关" });
    fireEvent.click(screen.getByTestId("wiki-entries-toggle")); // user collapse
    // 有匹配（Gateway 摘要含"网关"）→ 搜索期间强制展开
    expect(screen.getByText("Gateway")).toBeTruthy();
    expect(screen.queryByText("DeerFlow")).toBeNull(); // 非匹配项被过滤
  });
});

describe("WikiPanel search filtering", () => {
  it("filters entries by title and summary (case-insensitive)", () => {
    renderPanel({ query: "gateway" });
    expect(screen.getByText("Gateway")).toBeTruthy();
    expect(screen.queryByText("DeerFlow")).toBeNull();
    expect(screen.queryByText("沙箱")).toBeNull();
  });

  it("matches against the summary too", () => {
    renderPanel({ query: "沙箱中执行" });
    expect(screen.getByText("沙箱")).toBeTruthy();
    expect(screen.queryByText("Gateway")).toBeNull();
  });

  it("shows the no-match empty state when nothing matches", () => {
    renderPanel({ query: "不存在的词" });
    expect(screen.getByText("没有匹配的条目")).toBeTruthy();
    expect(screen.queryByText("DeerFlow")).toBeNull();
  });
});

describe("WikiPanel selection", () => {
  it("selects rows via checkboxes; the batch bar is retired（2026-09-02）", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: DeerFlow" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: 沙箱" }));
    expect(screen.queryByTestId("wiki-batch-bar")).toBeNull();
    expect(screen.getByRole("checkbox", { name: "选择条目: DeerFlow" }).getAttribute("aria-checked")).toBe("true");
  });

  it("selects all rows via the header checkbox", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("checkbox", { name: "全选" }));
    for (const title of ["DeerFlow", "Gateway", "沙箱"]) {
      expect(screen.getByRole("checkbox", { name: `选择条目: ${title}` }).getAttribute("aria-checked")).toBe("true");
    }
  });

  it("clears the selection when the query changes", () => {
    const { rerender } = render(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <WikiPanel entries={ENTRIES} query="" onOpenEntry={rs.fn()} onDeleteEntry={rs.fn()} />
      </I18nContext.Provider>,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: DeerFlow" }));
    expect(screen.getByRole("checkbox", { name: "选择条目: DeerFlow" }).getAttribute("aria-checked")).toBe("true");

    rerender(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <WikiPanel entries={ENTRIES} query="网关" onOpenEntry={rs.fn()} onDeleteEntry={rs.fn()} />
      </I18nContext.Provider>,
    );
    // 过滤后仍存活的 Gateway 行选择被清空。
    expect(screen.getByRole("checkbox", { name: "选择条目: Gateway" }).getAttribute("aria-checked")).toBe("false");
  });

  it("batch-deletes the selected entries via the context menu after confirm", async () => {
    const handlers = renderPanel();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: DeerFlow" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: Gateway" }));
    // 批量栏退役后，批量删除唯一入口是右键菜单。
    fireEvent.contextMenu(screen.getByTestId("wiki-entry-row-a"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除所选" }));
    // 批量确认文案带计数，且保留再生成语义（runAfterMenuClose 延迟到菜单退场）。
    expect(await screen.findByText("删除 2 条百科条目？", undefined, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByText(/下次生成时会按最新材料重新创建/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(handlers.onDeleteEntry).toHaveBeenCalledTimes(2), { timeout: 2000 });
    const deleted = handlers.onDeleteEntry.mock.calls.map((call) => (call[0] as WikiEntrySummary).id);
    expect(deleted).toContain("a");
    expect(deleted).toContain("b");
  });
});

describe("WikiPanel context menu", () => {
  // NOTE: under happy-dom a Radix context menu can only complete ONE
  // open/close cycle per mounted tree — each test below performs exactly one
  // cycle and fully settles before cleanup (same constraint as the document
  // table's selection tests).
  const settleMenu = async () => {
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  };

  it("offers single-row actions on an unselected row and routes 打开详情", async () => {
    const handlers = renderPanel();
    fireEvent.contextMenu(screen.getByTestId("wiki-entry-row-b"));
    expect(await screen.findByRole("menuitem", { name: "打开详情" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "编辑条目" })).toBeTruthy();
    // 措辞对齐（2026-09-02）：右键即选中，单选菜单也用「删除所选」；退出选择态两态对称。
    expect(screen.getByRole("menuitem", { name: "删除所选" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "取消选择" })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "打开详情" }));
    await waitFor(() => expect(handlers.onOpenEntry).toHaveBeenCalledWith(ENTRIES[1]), { timeout: 2000 });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  });

  it("right-clicking an unselected row selects just that row", async () => {
    renderPanel();
    fireEvent.contextMenu(screen.getByTestId("wiki-entry-row-b"));
    expect(await screen.findByRole("menuitem", { name: "打开详情" })).toBeTruthy();
    // 单选该行：菜单打开时背景 aria-hidden，用 getByLabelText 查行复选框。
    expect(screen.getByLabelText("选择条目: Gateway").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByLabelText("选择条目: DeerFlow").getAttribute("aria-checked")).toBe("false");
    await settleMenu();
  });

  it("offers batch actions when right-clicking inside a multi-selection", async () => {
    renderPanel();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: DeerFlow" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: Gateway" }));
    fireEvent.contextMenu(screen.getByTestId("wiki-entry-row-a"));
    expect(await screen.findByRole("menuitem", { name: "删除所选" })).toBeTruthy();
    // 批量栏退役后，计数反馈唯一载体是菜单标签。
    expect(screen.getAllByText("已选 2 项").length).toBeGreaterThan(0);
    await settleMenu();
  });

  // ── 局部更新/重建（2026-09-02）：右键「更新条目」重生成手选条目 ──────────────
  it("single-row 更新条目 regenerates just that entry (局部更新)", async () => {
    const handlers = renderPanel();
    fireEvent.contextMenu(screen.getByTestId("wiki-entry-row-b"));
    // 普通动作区（编辑条目之后、取消选择之前），带 RefreshCw 图标。
    const updateItem = await screen.findByRole("menuitem", { name: "更新条目" });
    expect(updateItem.querySelector("svg")).toBeTruthy();
    fireEvent.click(updateItem);
    // runAfterMenuClose 把动作延到菜单退场后（rAF），等一帧窗口。
    await waitFor(() => expect(handlers.onRegenerateEntries).toHaveBeenCalledWith(["b"]), { timeout: 2000 });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  });

  it("multi-selection 更新所选 regenerates the whole selected set", async () => {
    const handlers = renderPanel();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: DeerFlow" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择条目: Gateway" }));
    fireEvent.contextMenu(screen.getByTestId("wiki-entry-row-a"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "更新所选" }));
    await waitFor(() => expect(handlers.onRegenerateEntries).toHaveBeenCalledTimes(1), { timeout: 2000 });
    const ids = handlers.onRegenerateEntries.mock.calls[0]![0] as string[];
    expect(ids).toContain("a");
    expect(ids).toContain("b");
    expect(ids).toHaveLength(2);
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  });

  it("更新条目 is disabled while a generation run is in flight", async () => {
    const handlers = renderPanel({ updating: true });
    fireEvent.contextMenu(screen.getByTestId("wiki-entry-row-b"));
    const updateItem = await screen.findByRole("menuitem", { name: "更新条目" });
    expect(updateItem.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(updateItem);
    expect(handlers.onRegenerateEntries).not.toHaveBeenCalled();
    await settleMenu();
  });
});
