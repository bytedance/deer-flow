/**
 * 表格行卡在切片卡里的原生渲染（spec 2026-09-09 §8，plan Task 6）。
 *
 * markdown 模式行卡是合法 GFM 管道表 → ChunkCard 的 MarkdownContent（streamdown +
 * remark-gfm，见 core/streamdown/plugins.ts 的 sharedRemarkPlugins）**原生渲染为真
 * `<table>`**，零前端改动；linearized 模式行卡是 `列名: 值 | ...` 文本行（无分隔行，
 * 非 GFM 表）→ 渲染为纯文本、不生成 `<table>`。散文 chunk 渲染回归恒绿（旧行为不变）。
 */
import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { ChunkCard } from "@/components/workspace/knowledge/chunk-card";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";

function renderCard(text: string) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <ChunkCard text={text} />
    </I18nContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
});

// markdown 模式行卡：Task 4 chunker 产出的 GFM 管道表（重复表头 + 分隔行 + 行组）。
const MARKDOWN_ROW_CARD = [
  "| Region | Product | Q1 |",
  "| --- | --- | --- |",
  "| 华北 | Widget-A | 100 |",
  "| 华东 | Widget-B | 101 |",
].join("\n");

// linearized 模式行卡：每行 `列名: 值 | 列名: 值`（spec §7 消融态，非 GFM 表）。
const LINEARIZED_ROW_CARD = [
  "Region: 华北 | Product: Widget-A | Q1: 100",
  "Region: 华东 | Product: Widget-B | Q1: 101",
].join("\n");

describe("ChunkCard 表格行卡渲染（spec 2026-09-09 §8）", () => {
  it("markdown 模式行卡原生渲染为真 <table>（表头 th + 数据 td）", () => {
    const { container } = renderCard(MARKDOWN_ROW_CARD);
    const table = container.querySelector("table");
    expect(table).toBeTruthy();
    // 表头列名进 <th>，数据行进 <td>——即前端把行卡渲染为真表格（零改动）。
    const headers = [...container.querySelectorAll("th")].map((th) => th.textContent);
    expect(headers).toContain("Region");
    expect(headers).toContain("Product");
    const cells = [...container.querySelectorAll("td")].map((td) => td.textContent);
    expect(cells).toContain("华北");
    expect(cells).toContain("Widget-A");
  });

  it("linearized 模式行卡渲染为文本行，不生成 <table>", () => {
    const { container } = renderCard(LINEARIZED_ROW_CARD);
    expect(container.querySelector("table")).toBeNull();
    // 线性句子原样呈现（列名: 值），供窄上下文模型消融对比。
    expect(container.textContent).toContain("Region: 华北");
    expect(container.textContent).toContain("Product: Widget-B");
  });

  it("散文 chunk 渲染回归：无表格、正文原样（旧行为不变）", () => {
    const prose = "知识库系统将非结构化文档转化为可检索的知识资产。";
    const { container } = renderCard(prose);
    expect(container.querySelector("table")).toBeNull();
    expect(container.textContent).toContain(prose);
  });

  it("表格行卡无 fullscreen 扩大按钮，且表格沉入隐式 ScrollArea（2026-09-10 UI 对齐）", () => {
    const { container } = renderCard(MARKDOWN_ROW_CARD);
    // fullscreen 扩大效果退役（controls.table.fullscreen=false）：工具条不再渲染该按钮，
    // 其 buggy overlay（按钮无效 + 点击穿透退出详情）随之消失；copy/download 保留。
    expect(screen.queryByLabelText(/fullscreen/i)).toBeNull();
    // 表格沉入 ScrollArea（隐式滑条，aa02a307 同款）：table 在 scroll-area viewport 内，
    // 横滚由 ScrollArea 承担而非 streamdown 外壳的原生粗滑条。
    const viewport = container.querySelector('[data-slot="scroll-area-viewport"]');
    expect(viewport).toBeTruthy();
    expect(viewport!.querySelector("table")).toBeTruthy();
  });
});
