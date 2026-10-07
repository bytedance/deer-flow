/**
 * tab 行折叠呈现（spec 2026-09-28-kb-tabs-overflow §3 / D1 乙 / D3 / D6）：
 * - 溢出（scrollWidth > clientWidth）⇒ 行尾渐隐遮罩按钮（chevron + `tabs.more`
 *   aria-label）；不溢出 ⇒ 遮罩与下拉都不渲染（宽栏零变化）；
 * - 下拉项 = 固定折叠边界之后的尾巴（computeFoldCount），文案复用 tabs.*；
 * - 选中项回调 onTabChange（值 = 该项 tab 值）；`tabs.more` zh/en 值断言。
 * 测量注入（Task 0.3 配方）：prototype getter 按元素身份分发——容器
 * clientWidth/scrollWidth、trigger offsetLeft/offsetWidth；afterEach 还原。
 * 菜单开合照 composer-reasoning-controls 先例：keyDown ArrowDown（happy-dom
 * 下 click 不开 Radix 菜单，click-open 归 Task 3 真浏览器）。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Tabs } from "@/components/ui/tabs";
import { TabStrip } from "@/components/workspace/knowledge/tab-strip";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

// 首期收窄后中间栏只剩「文档」；溢出机制测试自备多 tab 夹具（标签自足，
// 不依赖已切标签页的 i18n 键）。
const L = {
  documents: "文档",
  wiki: "百科",
  recall: "检索测试",
  vectors: "向量空间",
  graph: "知识图谱",
  eval: "评测",
} as const;

const TABS = [
  { value: "documents", label: L.documents },
  { value: "wiki", label: L.wiki },
  { value: "recall", label: L.recall },
  { value: "vectors", label: L.vectors },
  { value: "graph", label: L.graph },
  { value: "eval", label: L.eval },
] as const;

const PINNED_KEYS = [
  "clientWidth",
  "scrollWidth",
  "offsetLeft",
  "offsetWidth",
] as const;
const originalDescriptors = new Map<string, PropertyDescriptor | undefined>();

function pinLayout(input: {
  containerWidth: number;
  ends: readonly number[];
  scrollWidth: number;
}) {
  for (const key of PINNED_KEYS) {
    originalDescriptors.set(
      key,
      Object.getOwnPropertyDescriptor(HTMLElement.prototype, key),
    );
    Object.defineProperty(HTMLElement.prototype, key, {
      configurable: true,
      get(this: HTMLElement) {
        if (this.dataset.testid === "tab-strip-scroll") {
          if (key === "scrollWidth") return input.scrollWidth;
          if (key === "clientWidth") return input.containerWidth;
          return 0;
        }
        if (this.getAttribute("data-slot") === "tabs-trigger") {
          const index = Array.from(
            document.querySelectorAll("[data-slot='tabs-trigger']"),
          ).indexOf(this);
          const end = input.ends[index] ?? 0;
          if (key === "offsetLeft") return end - 10;
          if (key === "offsetWidth") return 10;
        }
        return 0;
      },
    });
  }
}

function restoreLayout() {
  for (const key of PINNED_KEYS) {
    const descriptor = originalDescriptors.get(key);
    if (descriptor) {
      Object.defineProperty(HTMLElement.prototype, key, descriptor);
    } else {
      Reflect.deleteProperty(HTMLElement.prototype, key);
    }
  }
  originalDescriptors.clear();
}

function renderStrip(onTabChange = rs.fn()) {
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <Tabs value="documents" onValueChange={() => undefined}>
        <TabStrip activeTab="documents" tabs={TABS} onTabChange={onTabChange} />
      </Tabs>
    </I18nContext.Provider>,
  );
  return onTabChange;
}

function openMaskMenu() {
  fireEvent.keyDown(screen.getByTestId("tab-strip-mask"), { key: "ArrowDown" });
}

afterEach(() => {
  cleanup();
  restoreLayout();
});

describe("TabStrip 折叠呈现（D1 乙 / D3 / D6）", () => {
  it("① 溢出：渲染遮罩按钮（含 chevron）", () => {
    pinLayout({
      containerWidth: 300,
      ends: [70, 140, 210, 250, 330, 420],
      scrollWidth: 460,
    });
    renderStrip();
    const mask = screen.getByTestId("tab-strip-mask");
    expect(mask.querySelector("svg")).toBeTruthy();
  });

  it("② 不溢出：无遮罩无下拉、六 trigger 全在（宽栏零变化）", () => {
    pinLayout({
      containerWidth: 500,
      ends: [60, 120, 180, 240, 300, 360],
      scrollWidth: 360,
    });
    renderStrip();
    expect(screen.queryByTestId("tab-strip-mask")).toBeNull();
    expect(screen.getAllByRole("tab")).toHaveLength(6);
  });

  it("③ 下拉项 = 折叠边界尾巴（N=4 ⇒ 恰为第 5、6 项），文案复用 tabs.*", () => {
    pinLayout({
      containerWidth: 300,
      ends: [70, 140, 210, 250, 330, 420],
      scrollWidth: 460,
    });
    renderStrip();
    openMaskMenu();
    const items = screen.getAllByRole("menuitem");
    expect(items.map((node) => node.textContent)).toEqual([L.graph, L.eval]);
    expect(screen.queryByRole("menuitem", { name: L.documents })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: L.recall })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: L.vectors })).toBeNull();
  });

  it("④ 遮罩按钮开下拉（keyDown 照先例开 Radix 菜单）", () => {
    pinLayout({
      containerWidth: 300,
      ends: [70, 140, 210, 250, 330, 420],
      scrollWidth: 460,
    });
    renderStrip();
    openMaskMenu();
    expect(screen.getByRole("menu")).toBeTruthy();
  });

  it("⑤ 选中下拉项回调 onTabChange（值 = 该项 tab 值）", () => {
    pinLayout({
      containerWidth: 300,
      ends: [70, 140, 210, 250, 330, 420],
      scrollWidth: 460,
    });
    const onSelect = renderStrip();
    openMaskMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: L.eval }));
    expect(onSelect).toHaveBeenCalledWith("eval");
  });

  it("⑥ tabs.more 三文件同在（zh/en 值断言 + 遮罩 aria-label 接线）", () => {
    expect(zhCN.knowledge.tabs.more).toBe("更多标签页");
    expect(enUS.knowledge.tabs.more).toBe("More tabs");
    pinLayout({
      containerWidth: 300,
      ends: [70, 140, 210, 250, 330, 420],
      scrollWidth: 460,
    });
    renderStrip();
    expect(
      screen.getByTestId("tab-strip-mask").getAttribute("aria-label"),
    ).toBe(zhCN.knowledge.tabs.more);
  });

  it("⑦ 激活项滚入有效可见区（扣遮罩宽；切回时对齐左缘）", () => {
    pinLayout({
      containerWidth: 300,
      ends: [70, 140, 210, 250, 330, 420],
      scrollWidth: 460,
    });
    type TabValue = (typeof TABS)[number]["value"];
    const element = (tab: TabValue) => (
      <I18nContext.Provider
        value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
      >
        <Tabs value={tab} onValueChange={() => undefined}>
          <TabStrip activeTab={tab} tabs={TABS} onTabChange={() => undefined} />
        </Tabs>
      </I18nContext.Provider>
    );
    const { rerender } = render(element("documents"));
    const container = screen.getByTestId("tab-strip-scroll");
    expect(container.scrollLeft).toBe(0);
    rerender(element("eval"));
    // eval 尾端 420、有效可见区 300-40=260 ⇒ 落点 160（尾端贴遮罩左缘、
    // 不停在 40px 遮罩下）。
    expect(container.scrollLeft).toBe(160);
    rerender(element("documents"));
    // documents 起点 60 < 当前 160 ⇒ 对齐左缘（另一半分支）。
    expect(container.scrollLeft).toBe(60);
  });

  it("⑧ 溢出时滚动内容尾垫 40px（滚入落点可达），不溢出不垫", () => {
    pinLayout({
      containerWidth: 300,
      ends: [70, 140, 210, 250, 330, 420],
      scrollWidth: 460,
    });
    renderStrip();
    expect(screen.getByTestId("tab-strip-tail-pad")).toBeTruthy();
    cleanup();
    restoreLayout();
    pinLayout({
      containerWidth: 500,
      ends: [60, 120, 180, 240, 300, 360],
      scrollWidth: 360,
    });
    renderStrip();
    expect(screen.queryByTestId("tab-strip-tail-pad")).toBeNull();
  });
});
