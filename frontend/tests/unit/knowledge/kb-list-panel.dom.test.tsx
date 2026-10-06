/**
 * Left column of the knowledge page (spec §5.2): the 个人知识库 group with
 * the header「+」create dialog, selection state, and empty-state copy.
 * Purely presentational — data and mutations arrive via props.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { KbListPanel } from "@/components/workspace/knowledge/kb-list-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeBase } from "@/core/knowledge/types";

const KB_A: KnowledgeBase = {
  id: "kb-a",
  owner_id: "user-1",
  name: "产品资料",
  description: "",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};
const KB_B: KnowledgeBase = { ...KB_A, id: "kb-b", name: "研发文档" };
const KB_C: KnowledgeBase = { ...KB_A, id: "kb-c", name: "市场竞品" };

function renderPanel(props?: Partial<Parameters<typeof KbListPanel>[0]>) {
  const onSelect = rs.fn();
  const onCreate = rs.fn().mockResolvedValue(undefined);
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <KbListPanel
        kbs={[KB_A, KB_B]}
        selectedKbId={null}
        onSelect={onSelect}
        onCreate={onCreate}
        {...props}
      />
    </I18nContext.Provider>,
  );
  return { onSelect, onCreate };
}

afterEach(cleanup);

describe("KbListPanel", () => {
  it("renders the 个人知识库 group with every kb", () => {
    renderPanel();
    expect(screen.getByText("个人知识库")).toBeTruthy();
    // 分组标题带醒目图标（2026-09-10）：图标沉在标题 span 内（非邻接按钮）。
    expect(screen.getByText("个人知识库").querySelector("svg")).toBeTruthy();
    expect(screen.getByText("产品资料")).toBeTruthy();
    expect(screen.getByText("研发文档")).toBeTruthy();
  });

  it("invokes onSelect when a kb row is clicked", () => {
    const { onSelect } = renderPanel();
    fireEvent.click(screen.getByText("研发文档"));
    expect(onSelect).toHaveBeenCalledWith("kb-b");
  });

  describe("拖拽重排", () => {
    function renderReorderable() {
      const onReorder = rs.fn();
      render(
        <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
          <KbListPanel
            kbs={[KB_A, KB_B, KB_C]}
            selectedKbId={null}
            onSelect={() => undefined}
            onCreate={() => undefined}
            onReorder={onReorder}
          />
        </I18nContext.Provider>,
      );
      const rowOf = (name: string) => screen.getByText(name).closest("li")!;
      return { onReorder, rowOf };
    }

    it("moves the lifted row live when crossing another row", () => {
      const { onReorder, rowOf } = renderReorderable();
      fireEvent.dragStart(rowOf("产品资料"));
      // Sortable-style: the swap is reported on crossing, not on drop.
      fireEvent.dragOver(rowOf("市场竞品"));
      expect(onReorder).toHaveBeenCalledWith("kb-a", "kb-c");
      // Repeated dragover on the same row must not re-commit the move.
      fireEvent.dragOver(rowOf("市场竞品"));
      expect(onReorder).toHaveBeenCalledTimes(1);
      fireEvent.drop(rowOf("市场竞品"));
      fireEvent.dragEnd(rowOf("产品资料"));
    });

    it("marks the lifted row and clears the marker on dragEnd", () => {
      const { rowOf } = renderReorderable();
      fireEvent.dragStart(rowOf("产品资料"));
      expect(rowOf("产品资料").getAttribute("data-drag-source")).toBe("true");
      fireEvent.dragEnd(rowOf("产品资料"));
      expect(rowOf("产品资料").getAttribute("data-drag-source")).toBeNull();
    });

    it("ignores a drop without a preceding drag", () => {
      const { onReorder, rowOf } = renderReorderable();
      fireEvent.drop(rowOf("市场竞品"));
      expect(onReorder).not.toHaveBeenCalled();
    });

    it("keeps rows static when no onReorder is provided", () => {
      renderPanel();
      const row = screen.getByText("产品资料").closest("li")!;
      expect(row.getAttribute("draggable")).toBeNull();
    });
  });

  it("folds its own column from the rightmost header button", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: "收起列表栏" })).toBeNull();

    cleanup();
    const onCollapse = rs.fn();
    renderPanel({ onCollapse });
    const collapse = screen.getByRole("button", { name: "收起列表栏" });
    fireEvent.click(collapse);
    expect(onCollapse).toHaveBeenCalledTimes(1);
    // Flush against the divider, opposite the middle header's restore button.
    expect(collapse.parentElement?.lastElementChild).toBe(collapse);
  });

  it("marks the selected kb row as current", () => {
    renderPanel({ selectedKbId: "kb-a" });
    const selected = screen.getByText("产品资料").closest("[data-active]");
    expect(selected?.getAttribute("data-active")).toBe("true");
    const other = screen.getByText("研发文档").closest("[data-active]");
    expect(other?.getAttribute("data-active")).toBe("false");
  });

  it("creates a kb through the header + dialog", () => {
    const { onCreate } = renderPanel({ kbs: [] });
    fireEvent.click(screen.getByRole("button", { name: "新建知识库" }));

    fireEvent.change(screen.getByPlaceholderText("知识库名称"), {
      target: { value: "市场部资料" },
    });
    fireEvent.change(screen.getByPlaceholderText("描述（可选）"), {
      target: { value: "对外材料" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    expect(onCreate).toHaveBeenCalledWith("市场部资料", "对外材料");
  });

  it("keeps the create submit disabled until a name is entered", () => {
    renderPanel({ kbs: [] });
    fireEvent.click(screen.getByRole("button", { name: "新建知识库" }));
    const submit = screen.getByRole("button", { name: "创建" });
    expect(submit.hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByPlaceholderText("知识库名称"), { target: { value: "x" } });
    expect(submit.hasAttribute("disabled")).toBe(false);
  });

  it("shows the empty-state copy when no kb exists", () => {
    renderPanel({ kbs: [] });
    expect(screen.getByText(/还没有知识库/)).toBeTruthy();
  });

  it("renders the display-only 共享知识库 preview group under the personal list", () => {
    const { onSelect } = renderPanel();
    expect(screen.getByText("共享知识库")).toBeTruthy();
    expect(screen.getByText("共享知识库").querySelector("svg")).toBeTruthy();
    // 「即将上线」徽章已退役（2026-09-10）。
    expect(screen.queryByText("即将上线")).toBeNull();
    const sharedRow = screen.getByText("团队共享库").closest("li")!;
    // 纯展示：行不是按钮、不可拖拽，点击也不触发选中。
    expect(sharedRow.querySelector("button")).toBeNull();
    expect(sharedRow.getAttribute("draggable")).toBeNull();
    fireEvent.click(screen.getByText("团队共享库"));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("folds a group when its header label is clicked, and restores on second click", () => {
    renderPanel();
    // 个人组：标题即折叠开关（aria-expanded 跟状态），收起后行消失、再点恢复。
    const personal = screen.getByText("个人知识库").closest("button")!;
    expect(personal.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(personal);
    expect(personal.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("产品资料")).toBeNull();
    fireEvent.click(personal);
    expect(screen.getByText("产品资料")).toBeTruthy();

    // 共享组同款折叠。
    const shared = screen.getByText("共享知识库").closest("button")!;
    fireEvent.click(shared);
    expect(screen.queryByText("团队共享库")).toBeNull();
    fireEvent.click(shared);
    expect(screen.getByText("团队共享库")).toBeTruthy();
  });
});
