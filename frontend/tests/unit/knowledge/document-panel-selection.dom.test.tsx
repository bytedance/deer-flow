/**
 * Selection and right-click interactions of the document table (spec §5.2):
 * checkbox multi-select (header select-all with indeterminate state), the
 * Radix context menu (查看切片/生成考题/取消选择/删除所选, batch variant
 * when right-clicking a selected row), and batch delete through the shared
 * confirm dialog. 批量操作栏已退役（2026-09-02）：批量动作全由右键菜单
 * 承接，工具栏搜索/排序常驻不切换。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DocumentPanel } from "@/components/workspace/knowledge/document-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeBase, KnowledgeDocument } from "@/core/knowledge/types";

const KB: KnowledgeBase = {
  id: "kb-1",
  owner_id: "user-1",
  name: "产品资料",
  description: "",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};

function doc(partial: Partial<KnowledgeDocument>): KnowledgeDocument {
  return {
    id: "doc-1",
    kb_id: "kb-1",
    uploader_id: "user-1",
    name: "产品手册.pdf",
    size_bytes: 2048,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: 12,
    error: null,
    path_status: null,
    content_hash: null,
    created_at: "2026-08-09T10:00:00Z",
    ...partial,
  };
}

function renderPanel(props?: Partial<Parameters<typeof DocumentPanel>[0]>) {
  const handlers = {
    onUpload: rs.fn(),
    onDeleteDocument: rs.fn().mockResolvedValue(undefined),
    onRetryDocument: rs.fn(),
    onOpenChunks: rs.fn(),
  };
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <DocumentPanel kb={KB} documents={[doc({})]} supportedSuffixes={[".md", ".pdf", ".txt"]} {...handlers} {...props} />
    </I18nContext.Provider>,
  );
  return handlers;
}

afterEach(async () => {
  // happy-dom crashes (stack overflow inside the rstest worker) when cleanup
  // unmounts the tree while a Radix context menu is still open or animating
  // closed; always settle the menu first. Real browsers are unaffected.
  if (document.querySelector('[role="menu"]')) {
    fireEvent.keyDown(document.body, { key: "Escape" });
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  cleanup();
});

const DOCS = [
  doc({ id: "a", name: "产品手册.pdf" }),
  doc({ id: "b", name: "Roadmap.md" }),
  doc({ id: "c", name: "研发规范.docx" }),
];

function rows(): HTMLElement[] {
  return [...document.querySelectorAll("tbody tr")] as HTMLElement[];
}

describe("DocumentPanel selection", () => {
  it("selects rows via checkboxes; the batch bar is retired（2026-09-02）", () => {
    renderPanel({ documents: DOCS });
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: 产品手册.pdf" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: 研发规范.docx" }));
    // 批量栏不再出现；选中态由行复选框自身承载。
    expect(screen.queryByTestId("document-batch-bar")).toBeNull();
    expect(screen.getByRole("checkbox", { name: "选择文档: 产品手册.pdf" }).getAttribute("aria-checked")).toBe("true");
    // 工具栏不再随选中切换：搜索/排序常驻。
    expect(screen.getByPlaceholderText("搜索文档…")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: 研发规范.docx" }));
    expect(screen.getByRole("checkbox", { name: "选择文档: 研发规范.docx" }).getAttribute("aria-checked")).toBe("false");
  });

  it("selects all rows via the header checkbox and reports an indeterminate state", () => {
    renderPanel({ documents: DOCS });
    const selectAll = screen.getByRole("checkbox", { name: "全选" });
    fireEvent.click(selectAll);
    expect(selectAll.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: Roadmap.md" }));
    expect(selectAll.getAttribute("aria-checked")).toBe("mixed");
    fireEvent.click(screen.getByRole("checkbox", { name: "全选" }));
    expect(selectAll.getAttribute("aria-checked")).toBe("true");
  });

  it("batch-deletes the selected documents via the context menu after confirm", async () => {
    const handlers = renderPanel({ documents: DOCS });
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: 产品手册.pdf" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: Roadmap.md" }));
    // 批量栏退役后，批量删除唯一入口是右键菜单（runAfterMenuClose 延迟到菜单退场）。
    fireEvent.contextMenu(rows()[0]!);
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除所选" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }, { timeout: 3000 }));
    await waitFor(() => expect(handlers.onDeleteDocument).toHaveBeenCalledTimes(2), { timeout: 2000 });
    const deleted = handlers.onDeleteDocument.mock.calls.map((call) => call[0]);
    expect(deleted).toContain("a");
    expect(deleted).toContain("b");
  });
});

describe("DocumentPanel context menu", () => {
  // NOTE: under happy-dom a Radix context menu can only complete ONE
  // open/close cycle per mounted tree — a second contextmenu on the same
  // instance never opens, and unmounting mid-animation crashes the rstest
  // worker. Each test below therefore performs exactly one cycle and fully
  // settles before cleanup. Real browsers handle repeated cycles fine
  // (verified live).
  const settleMenu = async () => {
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  };

  it("offers single-row actions on an unselected row and routes them", async () => {
    const handlers = renderPanel({ documents: DOCS });
    fireEvent.contextMenu(rows()[1]!);
    expect(await screen.findByRole("menuitem", { name: "查看切片" })).toBeTruthy();
    // 措辞对齐（2026-09-02）：右键即选中，单选菜单也用「删除所选」。
    expect(screen.getByRole("menuitem", { name: "删除所选" })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "查看切片" }));
    // onOpenChunks is deferred until the menu's dismissal layer fully tears
    // down (runAfterMenuClose), so it arrives asynchronously.
    await waitFor(() => expect(handlers.onOpenChunks).toHaveBeenCalledWith(DOCS[1]), { timeout: 2000 });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
  });

  it("offers batch actions when right-clicking inside a multi-selection", async () => {
    renderPanel({ documents: DOCS });
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: 产品手册.pdf" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择文档: Roadmap.md" }));
    fireEvent.contextMenu(rows()[0]!);
    expect(await screen.findByRole("menuitem", { name: "删除所选" })).toBeTruthy();
    // 批量栏退役后，计数反馈唯一载体是菜单标签。
    expect(screen.getAllByText("已选 2 项").length).toBeGreaterThan(0);
    await settleMenu();
  });
});
