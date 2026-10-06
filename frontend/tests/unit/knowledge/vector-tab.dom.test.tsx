/**
 * 向量空间 tab（2026-08-15 spec）：
 * - Task 5 挂载骨架：中栏第四 tab trigger/切换/forceMount keep-alive。
 * - Task 6 面板本体（VectorTab）：工具栏（collection chips / 2D·3D / 算法 /
 *   重新计算）+ 加载·空·错误三态 + 索引中提示 + 四类单色分组（2026-08-15
 *   UX 迭代拍板）+ 点击联动现有抽屉链路。echarts 画布（vector-canvas）在
 *   jsdom 不可运行，整体 mock 断言 props。
 * - 聚焦交互（2026-09-05 全量搜索泛化）：搜索框匹配四类点 label → 命中点
 *   id 集合作为 searchedPointIds 传画布（锁定聚焦）；范围下拉限定匹配类别；
 *   命中芯片按类计数；hover 聚焦与淡化判定在 vector-canvas（isPointDimmed
 *   纯函数，见 vector-canvas.unit.test.ts）。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { toast } from "sonner";

import { KB_TOASTER_ID } from "@/components/workspace/knowledge/kb-toast";
import { MiddleTabs, type KnowledgeMiddleTab } from "@/components/workspace/knowledge/middle-tabs";
import { VectorTab } from "@/components/workspace/knowledge/vector-tab";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { useVectorProjection } from "@/core/knowledge/hooks";
import type { KnowledgeBase, VectorProjectionResponse } from "@/core/knowledge/types";

const hooksMock = rs.hoisted(() => ({
  useVectorProjection: rs.fn(),
  useProjectVectorQuery: rs.fn(),
  useRecomputeVectorProjection: rs.fn(),
}));

rs.mock("@/core/knowledge/hooks", () => ({
  useVectorProjection: hooksMock.useVectorProjection,
  useProjectVectorQuery: hooksMock.useProjectVectorQuery,
  useRecomputeVectorProjection: hooksMock.useRecomputeVectorProjection,
}));

// P6 联动提示（指纹漂移 / umap 禁用）走 sonner toast。
rs.mock("sonner", () => ({
  toast: { info: rs.fn(), success: rs.fn(), warning: rs.fn(), error: rs.fn() },
}));

/** echarts 画布 mock：记录 props，不渲染（jsdom 无 WebGL/canvas）。 */
const canvasMock = rs.hoisted(() => ({
  props: undefined as Record<string, unknown> | undefined,
}));

rs.mock("@/components/workspace/knowledge/vector-canvas", () => ({
  default: (props: Record<string, unknown>) => {
    canvasMock.props = props;
    return null;
  },
}));

const KB: KnowledgeBase = {
  id: "kb-1",
  owner_id: "user-1",
  name: "产品资料",
  description: "",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};

function renderTabs() {
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
          eval={<div data-testid="eval-pane" />}
        />
      </I18nContext.Provider>
    );
  }
  render(<Harness />);
}

const stateOf = (testid: string) =>
  screen.getByTestId(testid).closest("[data-slot='tabs-content']")?.getAttribute("data-state");

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("MiddleTabs 向量空间 tab", () => {
  it("renders the fourth trigger 向量空间 alongside the existing three", () => {
    renderTabs();
    expect(screen.getByRole("tab", { name: "文档" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "百科" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "检索测试" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "向量空间" })).toBeTruthy();
  });

  it("activates the vectors pane on trigger selection (Radix automatic mode)", () => {
    renderTabs();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "向量空间" }));
    expect(stateOf("vectors-pane")).toBe("active");
    expect(stateOf("documents-pane")).toBe("inactive");
  });

  it("keeps all four panes mounted (forceMount keep-alive) after switching", () => {
    renderTabs();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "向量空间" }));
    for (const testid of ["documents-pane", "wiki-pane", "recall-pane", "vectors-pane"]) {
      expect(screen.getByTestId(testid)).toBeTruthy();
    }
    expect(stateOf("wiki-pane")).toBe("inactive");
    expect(stateOf("recall-pane")).toBe("inactive");
  });
});

// ── Task 6: VectorTab 面板本体 ────────────────────────────────────────────

const PROJECTION: VectorProjectionResponse = {
  kb_id: "kb-1",
  algo: "pca",
  dims: 2,
  model_version: "pca-v1",
  fingerprint: "sha1:abc",
  cached: false,
  computed_ms: 42,
  total_points: 7,
  shown_points: 7,
  sampled: false,
  points: [
    { id: "doc-1#0000", source_type: "chunk", x: 0.1, y: 0.2, label: "a.pdf", color_key: "doc-1", preview: "第一章切片" },
    { id: "doc-1#0001", source_type: "chunk", x: 0.2, y: 0.3, label: "a.pdf", color_key: "doc-1", preview: "第二章切片" },
    { id: "doc-2#0000", source_type: "chunk", x: 0.9, y: 0.8, label: "b.pdf", color_key: "doc-2", preview: "另一文档" },
    { id: "JVM", source_type: "entity", x: 0.5, y: 0.5, label: "JVM", color_key: "概念", preview: "Java 虚拟机" },
    { id: "GC", source_type: "entity", x: 0.6, y: 0.4, label: "GC", color_key: "概念", preview: "垃圾回收" },
    { id: "entry-1", source_type: "wiki", x: 0.4, y: 0.6, label: "JVM 条目", color_key: "wiki", preview: "JVM 条目" },
    { id: "card-1", source_type: "card", x: 0.3, y: 0.7, label: "速记", color_key: "card", preview: "速记" },
  ],
};

function mockProjectionQuery(value: Partial<ReturnType<typeof useVectorProjection>>) {
  hooksMock.useVectorProjection.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    ...value,
  });
}

function renderVectorTab(props?: Partial<Parameters<typeof VectorTab>[0]>) {
  const handlers = {
    onOpenChunk: rs.fn(),
    onOpenWikiEntry: rs.fn(),
    onOpenManualCard: rs.fn(),
  };
  const renderTab = (nextProps?: Partial<Parameters<typeof VectorTab>[0]>) => (
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <VectorTab kbId="kb-1" enabled indexingCount={0} {...handlers} {...nextProps} />
    </I18nContext.Provider>
  );
  const utils = render(renderTab(props));
  return { ...handlers, ...utils, renderTab };
}

describe("VectorTab 面板", () => {
  beforeEach(() => {
    canvasMock.props = undefined;
    hooksMock.useProjectVectorQuery.mockReturnValue({ mutate: rs.fn(), isPending: false });
    hooksMock.useRecomputeVectorProjection.mockReturnValue({ mutate: rs.fn(), isPending: false });
    mockProjectionQuery({ data: PROJECTION });
  });

  it("shows the computing placeholder while the projection loads", () => {
    mockProjectionQuery({ isLoading: true });
    renderVectorTab();
    expect(screen.getByText("计算投影中…")).toBeTruthy();
    expect(canvasMock.props).toBeUndefined();
  });

  it("renders the empty-state guidance for a kb without vectors (no canvas)", () => {
    mockProjectionQuery({ data: { ...PROJECTION, points: [], total_points: 0 } });
    renderVectorTab();
    expect(screen.getByText(/还没有向量数据/)).toBeTruthy();
    expect(canvasMock.props).toBeUndefined();
  });

  it("surfaces the backend error detail on failure (e.g. umap extra missing)", () => {
    mockProjectionQuery({ isError: true, error: new Error("umap-learn is not installed") });
    renderVectorTab();
    expect(screen.getByText(/投影加载失败/)).toBeTruthy();
    expect(screen.getByText(/umap-learn is not installed/)).toBeTruthy();
  });

  it("renders the toolbar: 4 collection chips, 2D/3D toggle, algo select, recompute", () => {
    renderVectorTab();
    for (const name of ["切片", "实体", "百科", "条目"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    // Radix ToggleGroup single 模式的 Item 带 role="radio"（button 元素上覆写）。
    expect(screen.getByRole("radio", { name: "2D" })).toBeTruthy();
    // 3D 与重新计算在 Task 7 接通——可用态。
    expect(screen.getByRole("radio", { name: "3D" })).toHaveProperty("disabled", false);
    // 重新计算：图标按钮，aria-label 兑底可访问名（窄栏设计迭代 2026-08-15）。
    expect(screen.getByRole("button", { name: "重新计算" })).toHaveProperty("disabled", false);
    // 「算法」label 已移除，算法选择器经 aria-label 保留可访问名。
    expect(screen.getByRole("combobox", { name: "算法" })).toBeTruthy();
  });

  it("工具栏钉 h-9 对齐表头 36px + 控件 h-6 + 去 border-b 改 inset 阴影（2026-09-02）", () => {
    renderVectorTab();
    const toolbar = screen.getByTestId("vector-toolbar");
    // 高度钉 h-9（36px）与文档/评测表头（thead h-9=36px）对齐；不再用 py-2
    // （py-2 + 控件 h-7=28 会撑到 44px，比表头高 8px）。
    expect(toolbar.className).toContain("h-9");
    expect(toolbar.className).not.toContain("py-2");
    // 控件缩到 h-6（24px）：24px 在 36px 栏占比 67%≈搜索框(28px)在 44px 栏的 64%，
    // 视觉协调（原 h-7=28 占 78% 显笨重）。
    expect(screen.getByRole("button", { name: "切片" }).className).toContain("h-6");
    // pb-1 光学补偿：控件缩小后纯几何居中(6/6)因下方 inset 发丝线仍显靠下，
    // pb-1 让控件几何偏上(top4/bottom8)、视觉居中——发丝线视觉重量与控件大小无关。
    expect(toolbar.className).toContain("pb-1");
    // 下方发丝线用 inset 阴影而非 border-b：border 参与盒高会击穿 36px 钉高；
    // 阴影不参与布局，仍保留与下方画布的分隔线。
    expect(toolbar.className).not.toContain("border-b");
    expect(toolbar.className).toContain("shadow-[inset_0_-1px_0_var(--border)]");
    // 搜索栏（工具栏上方那行）去掉 border-b——它就是工具栏的「上边线」，
    // 去掉后工具栏不再被上下两条线夹住，两栏靠留白分界。
    const searchRow = toolbar.previousElementSibling!;
    expect(searchRow.className).not.toContain("border-b");
    expect(searchRow.querySelector("input")).toBeTruthy();
  });

  it("groups points into four single-color series by source_type (2026-08-15 UX 迭代)", async () => {
    // 用户拍板：文档一多按个体分组太花——四类 collection 各一色，图例四项。
    renderVectorTab();
    await waitFor(() => expect(canvasMock.props).toBeTruthy());
    const series = canvasMock.props!.series as Array<{ key: string; sourceType: string; label: string; color: string; points: unknown[] }>;
    expect(series).toHaveLength(4);
    const byType = new Map(series.map((s) => [s.sourceType, s]));
    // chunk 全部聚为一组（不再按文档细分），图例名为固定文案
    expect(byType.get("chunk")?.label).toBe("切片");
    expect(byType.get("chunk")?.points).toHaveLength(3);
    // entity 同理（不再按类型细分）
    expect(byType.get("entity")?.label).toBe("实体");
    expect(byType.get("entity")?.points).toHaveLength(2);
    expect(byType.get("wiki")?.points).toHaveLength(1);
    expect(byType.get("card")?.points).toHaveLength(1);
    // 四类四色且互不相同
    const colors = series.map((s) => s.color);
    expect(new Set(colors).size).toBe(4);
  });

  it("passes dims=2 and the full collection selection to the projection query", () => {
    renderVectorTab();
    expect(hooksMock.useVectorProjection).toHaveBeenCalledWith(
      "kb-1",
      expect.objectContaining({ algo: "pca", dims: 2, collections: ["chunks", "entities", "wiki", "cards"] }),
      true,
    );
  });

  it("drops a collection from the query params when its chip is toggled off", () => {
    renderVectorTab();
    fireEvent.click(screen.getByRole("button", { name: "切片" }));
    const lastCall = hooksMock.useVectorProjection.mock.calls.at(-1);
    expect(lastCall?.[1].collections).toEqual(["entities", "wiki", "cards"]);
  });

  it("switches the algo param when the algorithm select changes to umap", () => {
    renderVectorTab();
    // jsdom 无 pointerCapture——对齐 human-input-card 先例用键盘打开 Radix Select。
    fireEvent.keyDown(screen.getByRole("combobox", { name: "算法" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: "UMAP" }));
    const lastCall = hooksMock.useVectorProjection.mock.calls.at(-1);
    expect(lastCall?.[1].algo).toBe("umap");
  });

  it("gates the projection query with the enabled flag (lazy tab activation)", () => {
    renderVectorTab({ enabled: false });
    expect(hooksMock.useVectorProjection).toHaveBeenCalledWith("kb-1", expect.anything(), false);
  });

  it("routes point clicks to the existing drawer chains (chunk/wiki/card), entity inert", async () => {
    const handlers = renderVectorTab();
    await waitFor(() => expect(canvasMock.props).toBeTruthy());
    const onPointClick = canvasMock.props!.onPointClick as (point: unknown) => void;

    onPointClick(PROJECTION.points[0]); // chunk: color_key=doc_id, id=chunk_id
    expect(handlers.onOpenChunk).toHaveBeenCalledWith("doc-1", "doc-1#0000");

    onPointClick(PROJECTION.points[5]); // wiki: id=entry_id
    expect(handlers.onOpenWikiEntry).toHaveBeenCalledWith("entry-1");

    onPointClick(PROJECTION.points[6]); // card: id=card_id
    expect(handlers.onOpenManualCard).toHaveBeenCalledWith("card-1");

    handlers.onOpenChunk.mockClear();
    handlers.onOpenWikiEntry.mockClear();
    handlers.onOpenManualCard.mockClear();
    onPointClick(PROJECTION.points[3]); // entity: 无抽屉目标——不触发任何联动
    expect(handlers.onOpenChunk).not.toHaveBeenCalled();
    expect(handlers.onOpenWikiEntry).not.toHaveBeenCalled();
    expect(handlers.onOpenManualCard).not.toHaveBeenCalled();
  });

  it("shows the indexing hint while documents are still being indexed", () => {
    renderVectorTab({ indexingCount: 2 });
    expect(screen.getByText(/2 个文档索引中/)).toBeTruthy();
  });

  // ── Task 7: 3D 切换 + 采样徽标 + 重新计算 ──────────────────────────────

  it("switches to 3D: requests dims=3 and forwards dims=3 to the canvas", async () => {
    renderVectorTab();
    fireEvent.click(screen.getByRole("radio", { name: "3D" }));
    const lastCall = hooksMock.useVectorProjection.mock.calls.at(-1);
    expect(lastCall?.[1].dims).toBe(3);
    await waitFor(() => expect(canvasMock.props?.dims).toBe(3));
  });

  it("shows the sampling badge when the projection was subsampled", () => {
    mockProjectionQuery({
      data: { ...PROJECTION, sampled: true, shown_points: 5000, total_points: 12345 },
    });
    renderVectorTab();
    expect(screen.getByText("已抽样 5000/12345 点")).toBeTruthy();
  });

  it("hides the sampling badge when nothing was subsampled", () => {
    renderVectorTab();
    expect(screen.queryByText(/已抽样/)).toBeNull();
  });

  it("recompute triggers a forced refresh with the current view params", () => {
    const recomputeMutate = rs.fn();
    hooksMock.useRecomputeVectorProjection.mockReturnValue({ mutate: recomputeMutate, isPending: false });
    renderVectorTab();
    fireEvent.click(screen.getByRole("button", { name: "重新计算" }));
    expect(recomputeMutate).toHaveBeenCalledWith(
      expect.objectContaining({ collections: ["chunks", "entities", "wiki", "cards"], algo: "pca", dims: 2 }),
    );
  });

  // ── 聚焦交互（2026-09-05 全量搜索泛化）：搜索框锁定命中点聚焦 ─────────────────────────

  it("renders a search box that locks focus onto matching points of any type", async () => {
    renderVectorTab();
    await waitFor(() => expect(canvasMock.props).toBeTruthy());
    // 默认无搜索锁定
    expect(canvasMock.props!.searchedPointIds).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "搜索…" }), { target: { value: "a.pdf" } });
    await waitFor(() => {
      const ids = canvasMock.props!.searchedPointIds as ReadonlySet<string>;
      expect([...ids].sort()).toEqual(["doc-1#0000", "doc-1#0001"]);
    });
  });

  it("matches multiple documents by case-insensitive substring", async () => {
    renderVectorTab();
    await waitFor(() => expect(canvasMock.props).toBeTruthy());
    fireEvent.change(screen.getByRole("textbox", { name: "搜索…" }), { target: { value: ".PDF" } });
    await waitFor(() => {
      const ids = canvasMock.props!.searchedPointIds as ReadonlySet<string>;
      expect([...ids].sort()).toEqual(["doc-1#0000", "doc-1#0001", "doc-2#0000"]);
    });
  });

  it("clears the search lock when the query is emptied", async () => {
    renderVectorTab();
    await waitFor(() => expect(canvasMock.props).toBeTruthy());
    const search = screen.getByRole("textbox", { name: "搜索…" });
    fireEvent.change(search, { target: { value: "a" } });
    await waitFor(() => expect(canvasMock.props!.searchedPointIds).not.toBeNull());
    fireEvent.change(search, { target: { value: "" } });
    await waitFor(() => expect(canvasMock.props!.searchedPointIds).toBeNull());
  });

  it("全量搜索命中跨类点：实体/百科同词一起进入命中集（2026-09-05）", async () => {
    renderVectorTab();
    await waitFor(() => expect(canvasMock.props).toBeTruthy());
    fireEvent.change(screen.getByRole("textbox", { name: "搜索…" }), { target: { value: "JVM" } });
    await waitFor(() => {
      const ids = canvasMock.props!.searchedPointIds as ReadonlySet<string>;
      expect([...ids].sort()).toEqual(["JVM", "entry-1"]);
    });
  });

  it("范围筛选只匹配所选类：选「文档」后实体命中不参与（2026-09-05）", async () => {
    renderVectorTab();
    await waitFor(() => expect(canvasMock.props).toBeTruthy());
    fireEvent.keyDown(screen.getByRole("combobox", { name: "搜索范围" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: "文档" }));
    fireEvent.change(screen.getByRole("textbox", { name: "搜索…" }), { target: { value: "JVM" } });
    await waitFor(() => {
      const ids = canvasMock.props!.searchedPointIds as ReadonlySet<string>;
      expect(ids.size).toBe(0);
    });
    // 切回全部 → 命中恢复
    fireEvent.keyDown(screen.getByRole("combobox", { name: "搜索范围" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: "全部" }));
    await waitFor(() => {
      const ids = canvasMock.props!.searchedPointIds as ReadonlySet<string>;
      expect(ids.size).toBe(2);
    });
  });

  // ── 窄栏降级（2026-08-17 二迭代）：溢出检测 → chips 仅色点 + ⋯ 菜单 ─────

  it("collapses chips text and dims/algo into a ⋯ menu when the toolbar overflows", () => {
    // jsdom 无布局——把工具栏 scrollWidth 钉成大值模拟溢出（clientWidth 恒 0），
    // 降级应连升两档：chips 仅色点、2D/3D 与算法收进 ⋯ 菜单。
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollWidth");
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "vector-toolbar" ? 999 : 0;
      },
    });
    try {
      renderVectorTab();
      // 档1+：chips 文字移出 DOM，可访问名由 aria-label 保持
      expect(screen.getByRole("button", { name: "切片" })).toBeTruthy();
      expect(screen.queryByText("实体")).toBeNull();
      // 档2：内联 2D/3D 与算法 Select 消失，⋯ 按钮出现
      expect(screen.queryByRole("radio", { name: "2D" })).toBeNull();
      expect(screen.queryByRole("combobox", { name: "算法" })).toBeNull();
      const more = screen.getByRole("button", { name: "更多选项" });
      // 菜单内承载维度与算法切换（Radix 键盘开菜单，与上方 Select 测试同款先例）
      fireEvent.keyDown(more, { key: "ArrowDown" });
      fireEvent.click(screen.getByRole("menuitemradio", { name: "3D" }));
      const lastCall = hooksMock.useVectorProjection.mock.calls.at(-1);
      expect(lastCall?.[1].dims).toBe(3);
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });
});

// ── Task 8: P6 检索联动叠加（spec §9 双通道共享同一叠加渲染层）─────────────

describe("VectorTab 检索联动叠加", () => {
  const RECALL_OVERLAY = {
    source: "recall" as const,
    text: "Gateway 职责",
    hits: [
      { pointId: "doc-1#0000", score: 0.97 },
      { pointId: "doc-1#0001", score: null },
    ],
  };
  const CHAT_OVERLAY = {
    source: "chat" as const,
    text: "支持哪些格式？",
    hits: [{ pointId: "doc-2#0000", score: 0.9 }],
  };

  // 本 describe 独立于「VectorTab 面板」的 beforeEach——投影 mock 必须每用例
  // 重置（有用例会改 fingerprint，残留会污染后续用例的叠加判定）。
  beforeEach(() => {
    canvasMock.props = undefined;
    mockProjectionQuery({ data: PROJECTION });
  });

  /** 捕获 useProjectVectorQuery 的 mutate，返回后可手动触发 onSuccess。 */
  function setupProjectQuery() {
    const mutate = rs.fn();
    hooksMock.useProjectVectorQuery.mockReturnValue({ mutate, isPending: false });
    return mutate;
  }

  function succeedQuery(mutate: ReturnType<typeof rs.fn>, fingerprint = PROJECTION.fingerprint) {
    const options = mutate.mock.calls.at(-1)?.[1] as {
      onSuccess: (result: unknown) => void;
    };
    act(() =>
      options.onSuccess({ x: 0.11, y: 0.22, model_version: "pca-v1", fingerprint }),
    );
  }

  it("projects the overlay query text and forwards query point + hits to the canvas", async () => {
    const mutate = setupProjectQuery();
    renderVectorTab({ overlay: RECALL_OVERLAY });
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        "Gateway 职责",
        expect.objectContaining({ onSuccess: expect.any(Function) }),
      ),
    );
    succeedQuery(mutate);
    await waitFor(() => {
      const overlay = canvasMock.props?.overlay as {
        query: { x: number; y: number; label: string };
        hits: unknown[];
      } | null;
      expect(overlay?.query).toEqual({ x: 0.11, y: 0.22, label: "Gateway 职责" });
      expect(overlay?.hits).toEqual(RECALL_OVERLAY.hits);
    });
  });

  it("discards the overlay with a notice when the query result fingerprint drifts", async () => {
    const mutate = setupProjectQuery();
    renderVectorTab({ overlay: RECALL_OVERLAY });
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    succeedQuery(mutate, "sha1:stale");
    await waitFor(() => expect(canvasMock.props?.overlay ?? null).toBeNull());
    expect(toast.info).toHaveBeenCalledWith("投影已更新，检索叠加已失效——请重新触发检索", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
  });

  it("surfaces a notice instead of failing silently when the query projection errors", async () => {
    // 静默失败曾是用户可感 bug：409（缓存键错位）/500（embedder 故障）都无任何反馈。
    const mutate = setupProjectQuery();
    renderVectorTab({ overlay: RECALL_OVERLAY });
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    const options = mutate.mock.calls.at(-1)?.[1] as { onError: (error: Error) => void };
    act(() => options.onError(new Error("boom")));
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith("检索叠加失败——请重试", expect.objectContaining({ toasterId: KB_TOASTER_ID })));
    expect(canvasMock.props?.overlay ?? null).toBeNull();
  });

  it("drops the active overlay with a notice when the projection fingerprint changes", async () => {
    const mutate = setupProjectQuery();
    const { rerender, renderTab } = renderVectorTab({ overlay: RECALL_OVERLAY });
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    succeedQuery(mutate);
    await waitFor(() => expect(canvasMock.props?.overlay).toBeTruthy());

    // 重新计算 / 内容变更 → 投影指纹翻转 → 旧坐标系的叠加必须丢弃。
    mockProjectionQuery({ data: { ...PROJECTION, fingerprint: "sha1:def" } });
    rerender(renderTab({ overlay: RECALL_OVERLAY }));
    await waitFor(() => expect(canvasMock.props?.overlay ?? null).toBeNull());
    expect(toast.info).toHaveBeenCalledWith("投影已更新，检索叠加已失效——请重新触发检索", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
  });

  it("disables the overlay with a PCA-only notice under umap (spec §9 公共边界)", async () => {
    const mutate = setupProjectQuery();
    const { rerender, renderTab } = renderVectorTab();
    // jsdom 无 pointerCapture——Radix Select 键盘打开（先例见上方 algo 用例）。
    fireEvent.keyDown(screen.getByRole("combobox", { name: "算法" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: "UMAP" }));
    rerender(renderTab({ overlay: RECALL_OVERLAY }));
    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith("检索叠加仅支持 PCA 投影——请切回 PCA 后重试", expect.objectContaining({ toasterId: KB_TOASTER_ID })),
    );
    expect(mutate).not.toHaveBeenCalled();
  });

  it("follows chat overlays by default; freezing ignores new chat overlays but not recall ones", async () => {
    const mutate = setupProjectQuery();
    const { rerender, renderTab } = renderVectorTab({ overlay: CHAT_OVERLAY });
    // 开关默认开
    const followSwitch = screen.getByRole("switch", { name: "跟随对话" });
    expect(followSwitch.getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect(mutate).toHaveBeenCalledWith("支持哪些格式？", expect.anything()));
    succeedQuery(mutate);
    await waitFor(() => expect(canvasMock.props?.overlay).toBeTruthy());

    // 关闭「跟随对话」→ 新 chat overlay 冻结（不投影、画面保持）。
    fireEvent.click(followSwitch);
    const nextChat = { ...CHAT_OVERLAY, text: "新一轮提问" };
    rerender(renderTab({ overlay: nextChat }));
    await waitFor(() => expect(canvasMock.props?.overlay).toBeTruthy());
    expect(mutate).toHaveBeenCalledTimes(1);
    const frozen = canvasMock.props?.overlay as { query: { label: string } };
    expect(frozen.query.label).toBe("支持哪些格式？");

    // recall 显式动作不受开关影响。
    rerender(renderTab({ overlay: RECALL_OVERLAY }));
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
    expect(mutate).toHaveBeenLastCalledWith("Gateway 职责", expect.anything());
  });

  // ── 叠加徽标与清除（2026-08-19 UX 迭代）────────────────────────────────

  it("shows the overlay badge (query text + hit count) and clears the overlay on ×", async () => {
    const mutate = setupProjectQuery();
    renderVectorTab({ overlay: RECALL_OVERLAY });
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    succeedQuery(mutate);
    // 徽标：query 文本 + 命中数（两个命中都在 PROJECTION 里）
    await waitFor(() => expect(screen.getByTestId("vector-overlay-badge")).toBeTruthy());
    const badge = screen.getByTestId("vector-overlay-badge");
    expect(badge.textContent).toContain("Gateway 职责");
    expect(badge.textContent).toContain("命中 2/2");
    // × 清除 → 画布叠加撤掉 + 徽标消失
    fireEvent.click(screen.getByRole("button", { name: "清除叠加" }));
    await waitFor(() => expect(canvasMock.props?.overlay ?? null).toBeNull());
    expect(screen.queryByTestId("vector-overlay-badge")).toBeNull();
  });

  it("counts only hits present in the projection (silently-skipped hits become visible)", async () => {
    const mutate = setupProjectQuery();
    const sparseOverlay = {
      ...RECALL_OVERLAY,
      hits: [
        { pointId: "doc-1#0000", score: 0.9 },
        { pointId: "not-in-projection", score: 0.5 },
      ],
    };
    renderVectorTab({ overlay: sparseOverlay });
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    succeedQuery(mutate);
    await waitFor(() =>
      expect(screen.getByTestId("vector-overlay-badge").textContent).toContain("命中 1/2"),
    );
  });

  it("does not re-project the same overlay after clearing (no resurrection on re-render)", async () => {
    const mutate = setupProjectQuery();
    const { rerender, renderTab } = renderVectorTab({ overlay: RECALL_OVERLAY });
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
    succeedQuery(mutate);
    await waitFor(() => expect(screen.getByTestId("vector-overlay-badge")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "清除叠加" }));
    await waitFor(() => expect(screen.queryByTestId("vector-overlay-badge")).toBeNull());
    // 同一份 overlay 重渲染 → consumed 判定挡住，不复活、不重打 query 投影
    rerender(renderTab({ overlay: RECALL_OVERLAY }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("vector-overlay-badge")).toBeNull();
  });
});
