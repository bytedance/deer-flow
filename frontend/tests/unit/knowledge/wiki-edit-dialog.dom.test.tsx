/**
 * Wiki entry dual-mode editor (Phase-3 Batch-1 P1): two textareas for main
 * content (replaceable) and supplement layer (persistent), with form validation
 * and audit timestamp display.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WikiEditDialog } from "@/components/workspace/knowledge/wiki-edit-dialog";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { WikiEntryDetail } from "@/core/knowledge/types";

const MOCK_ENTRY: WikiEntryDetail = {
  id: "entry-1",
  kb_id: "kb-1",
  title: "Polymorphism",
  content: "Polymorphism is an OOP feature.",
  supplement_content: "User note: includes overloading and overriding",
  status: "ready",
  source_chunk_ids: ["chunk-1"],
  updated_at: "2026-08-15T10:00:00Z",
};

function renderDialog(entry: WikiEntryDetail | null = MOCK_ENTRY, open = true) {
  const onOpenChange = rs.fn();
  const onSave = rs.fn().mockResolvedValue(undefined);
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <WikiEditDialog entry={entry} open={open} onOpenChange={onOpenChange} onSave={onSave} />
    </I18nContext.Provider>,
  );
  return { onOpenChange, onSave };
}

afterEach(cleanup);

describe("WikiEditDialog", () => {
  it("renders both textareas when entry is provided", () => {
    renderDialog();
    expect(screen.getByLabelText(/主内容区/)).toBeTruthy();
    expect(screen.getByLabelText(/补充层/)).toBeTruthy();
  });

  it("pre-fills form with existing entry data", () => {
    renderDialog();
    const mainContent = screen.getByLabelText(/主内容区/);
    const supplement = screen.getByLabelText(/补充层/);
    expect((mainContent as HTMLTextAreaElement).value).toBe("Polymorphism is an OOP feature.");
    expect((supplement as HTMLTextAreaElement).value).toBe("User note: includes overloading and overriding");
  });

  it("keeps textareas constrained to the dialog width (min-w-0 chain) so long lines soft-wrap", () => {
    renderDialog();
    // field-sizing-content 的 textarea 把「内容不换行宽度」作为 min-content 贡献
    // 沿 grid/flex item 链向上传递撑宽对话框（修复前：卡片编辑器溢出 Dialog、
    // AI 编辑器出现横向滚动）。链上每个 flex 容器与 textarea 自身都要 min-w-0。
    for (const textarea of [screen.getByLabelText(/主内容区/), screen.getByLabelText(/补充层/)]) {
      let node: HTMLElement | null = textarea;
      while (node && node.getAttribute("data-slot") !== "dialog-content") {
        if (node.tagName === "TEXTAREA" || node.className.includes("flex")) {
          expect(node.className).toContain("min-w-0");
        }
        node = node.parentElement;
      }
    }
  });

  it("caps the ScrollArea root so the viewport stays a bounded scroll container (2026-09-04)", () => {
    renderDialog();
    // 对话框高度是 auto 被 max-h-[90vh] 截帽的 indefinite 高度：Viewport 的
    // height:100% 会回退 auto、被长内容撑到全高而失去滚动能力（滚轮失效、
    // 滚动条不出现的实测根因）。封顶加在 ScrollArea Root，由原语 Viewport 的
    // max-h-[inherit] 继承——两个 class 缺一不可，故在此钉住。
    const scrollRoot = document.querySelector('[data-slot="scroll-area"]');
    const viewport = document.querySelector('[data-slot="scroll-area-viewport"]');
    expect(scrollRoot?.className).toContain("max-h-[calc(90vh-3.5rem)]");
    expect(viewport?.className).toContain("max-h-[inherit]");
  });

  it("calls onSave with trimmed content and supplement on submit", async () => {
    const { onSave } = renderDialog();

    const mainContent = screen.getByLabelText(/主内容区/);
    const supplement = screen.getByLabelText(/补充层/);

    fireEvent.change(mainContent, { target: { value: "Updated main content  " } });
    fireEvent.change(supplement, { target: { value: "Updated supplement  " } });

    const saveButton = screen.getByRole("button", { name: "保存" });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith("entry-1", "Updated main content", "Updated supplement");
    });
  });

  it("disables save button when main content is empty", () => {
    renderDialog();

    const mainContent = screen.getByLabelText(/主内容区/);
    fireEvent.change(mainContent, { target: { value: "" } });

    const saveButton = screen.getByRole("button", { name: "保存" });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows audit timestamp when entry has updated_at", () => {
    renderDialog();
    expect(screen.getByText(/最后编辑时间/)).toBeTruthy();
  });

  it("closes dialog after successful save", async () => {
    const { onOpenChange } = renderDialog();

    const saveButton = screen.getByRole("button", { name: "保存" });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("handles null supplement_content gracefully", () => {
    const entryWithNullSupplement: WikiEntryDetail = {
      ...MOCK_ENTRY,
      supplement_content: null,
    };
    renderDialog(entryWithNullSupplement);

    const supplement = screen.getByLabelText(/补充层/);
    expect((supplement as HTMLTextAreaElement).value).toBe("");
  });

  it("sends null when supplement is trimmed to empty string", async () => {
    const { onSave } = renderDialog();

    const supplement = screen.getByLabelText(/补充层/);
    fireEvent.change(supplement, { target: { value: "   " } }); // Only whitespace

    const saveButton = screen.getByRole("button", { name: "保存" });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(
        "entry-1",
        "Polymorphism is an OOP feature.",
        null, // Should send null for empty supplement
      );
    });
  });

  it("describes the supplement layer as generation direction, not a mere annotation (2026-09-12)", () => {
    // 主内容区不再承诺"编辑会被融入新版本"：那条路没有实现，正文只会被覆盖。
    // 补充层则相反 —— 它真的会在每次重新生成时作为方向注入（spec 2026-09-12）。
    renderDialog();

    expect(screen.queryByText(/参考材料/)).toBeNull();
    expect(screen.getByText(/此内容会在下次重新生成时被覆盖/)).toBeTruthy();
    expect(
      screen.getByText(/每次重新生成都会作为你的要求带给 AI/),
    ).toBeTruthy();
  });
});
