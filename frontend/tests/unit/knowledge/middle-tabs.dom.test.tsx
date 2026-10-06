/**
 * 评测 tab 挂载（2026-08-24 spec §5，plan Task 4）：
 * - 第六个 trigger「评测」+ Radix 切换 + 六 pane forceMount keep-alive。
 * EvalTab 面板本体（数据联通/降档/drawer 占位，plan Task 5）见
 * eval-tab.dom.test.tsx。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";

import { MiddleTabs, type KnowledgeMiddleTab } from "@/components/workspace/knowledge/middle-tabs";
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

function renderTabs(evalPane?: ReactNode) {
  function Harness() {
    const [tab, setTab] = useState<KnowledgeMiddleTab>("documents");
    return (
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <MiddleTabs
          kb={KB}
          activeTab={tab}
          onTabChange={setTab}
          supportedSuffixes={[".md", ".pdf", ".txt"]}
          onUpload={rs.fn()}
          onGenerateWiki={rs.fn()}
          onRenameKb={rs.fn()}
          onDeleteKb={rs.fn()}
          documents={<div data-testid="documents-pane" />}
          wiki={<div data-testid="wiki-pane" />}
          recall={<div data-testid="recall-pane" />}
          vectors={<div data-testid="vectors-pane" />}
          graph={<div data-testid="graph-pane" />}
          eval={evalPane ?? <div data-testid="eval-pane" />}
        />
      </I18nContext.Provider>
    );
  }
  return render(<Harness />);
}

const stateOf = (testid: string) =>
  screen.getByTestId(testid).closest("[data-slot='tabs-content']")?.getAttribute("data-state");

describe("MiddleTabs 评测 tab 挂载", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders the sixth trigger labeled 评测", () => {
    renderTabs();
    expect(screen.getByRole("tab", { name: "评测" })).toBeTruthy();
  });

  it("activates the eval pane on trigger selection (Radix automatic mode)", () => {
    renderTabs();
    // Radix Tabs automatic 激活模式在 mousedown 触发（对齐 graph-tab 先例）。
    fireEvent.mouseDown(screen.getByRole("tab", { name: "评测" }));
    expect(stateOf("eval-pane")).toBe("active");
    expect(stateOf("documents-pane")).toBe("inactive");
  });

  it("keeps all six panes mounted when switching tabs (forceMount)", () => {
    renderTabs();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "评测" }));
    for (const testid of ["documents-pane", "wiki-pane", "recall-pane", "vectors-pane", "graph-pane", "eval-pane"]) {
      expect(screen.getByTestId(testid)).toBeTruthy();
    }
  });
});
