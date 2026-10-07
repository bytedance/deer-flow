/**
 * 中间栏容器（首期收窄）：单「文档」tab + 库头行（h-12 对齐会话栏）+ 库菜单（上传/重命名/删除）。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { MiddleTabs } from "@/components/workspace/knowledge/middle-tabs";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeBase } from "@/core/knowledge/types";

const KB: KnowledgeBase = {
  id: "kb-1",
  owner_id: "user-1",
  name: "产品资料",
  description: "",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};

function renderTabs() {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <MiddleTabs
        kb={KB}
        supportedSuffixes={[".md", ".pdf", ".txt"]}
        onUpload={rs.fn()}
        onRenameKb={rs.fn()}
        onDeleteKb={rs.fn()}
        documents={<div data-testid="documents-pane" />}
      />
    </I18nContext.Provider>,
  );
}

const stateOf = (testid: string) =>
  screen.getByTestId(testid).closest("[data-slot='tabs-content']")?.getAttribute("data-state");

describe("MiddleTabs 首期收窄", () => {
  afterEach(() => {
    cleanup();
  });

  it("sizes the library header row to h-12, matching the chat panel header", () => {
    // 两栏标题容器底线必须同一 y（2026-10-07 用户报错位 8px）：高度只能钉
    // 结构类名，真实像素由真浏览器量。
    renderTabs();
    const row = screen.getByTestId("knowledge-middle-header");
    expect(row.className).toContain("h-12");
    expect(row.className).toContain("border-b");
  });

  it("renders the single documents tab and its pane", () => {
    renderTabs();
    expect(screen.getByRole("tab", { name: "文档" })).toBeTruthy();
    expect(stateOf("documents-pane")).toBe("active");
  });

  it("keeps the library-level menu entries (upload / rename / delete)", () => {
    renderTabs();
    fireEvent.keyDown(screen.getByRole("button", { name: "设置" }), {
      key: "ArrowDown",
    });
    expect(screen.getByRole("menuitem", { name: "上传文档" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "重命名知识库" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "删除知识库" })).toBeTruthy();
  });
});
