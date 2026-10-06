/**
 * 评测 tab 数据联通（2026-08-24 spec §5，plan Task 5）：
 * - useMetricsOverview / useEvalTrend 经 mock 注入数据，断言 eval-tab 的
 *   loading / 错误 / 数据三态渲染与 props 透传；
 * - 趋势空态：has_data=false（新 KB 无评测历史）渲染空态提示而非空白画布
 *   （2026-08-26 补）；
 * - 视窗预设切换不 refetch（contract v4：服务端一次给 90d）——点击转发
 *   spanRequest 给 canvas，按钮高亮为密度指示器；
 * - drawer 占位（Task 6 替换为 EvalRunDrawer）；
 * - 窄面板降档：容器溢出（钉 scrollWidth 模拟）时粒度按钮组收进 ⋯ 菜单
 *   （vector-tab useToolbarTier 溢出检测先例）。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { toast } from "sonner";

const hooksMock = rs.hoisted(() => ({
  useMetricsOverview: rs.fn(),
  useEvalTrend: rs.fn(),
  useEvalRuns: rs.fn(),
  useTriggerEvalRun: rs.fn(),
  useCancelEvalRun: rs.fn(),
  // key factories 以真实实现同款内联——组件 drain 边失效要用，测试断言同一字面量。
  knowledgeEvalLatestKey: (kbId: string) => [
    "knowledge-bases",
    kbId,
    "eval-runs",
    "latest",
  ],
  knowledgeEvalTrendKey: (kbId: string) => [
    "knowledge-bases",
    kbId,
    "eval-runs",
    "trend",
  ],
  knowledgeEvalRunsKey: (kbId: string) => [
    "knowledge-bases",
    kbId,
    "eval-runs",
    "history",
  ],
}));

rs.mock("@/core/knowledge/hooks", () => hooksMock);

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

/** echarts 画布 mock：记录 props，渲染占位 div（jsdom 无 canvas）。 */
const canvasMock = rs.hoisted(() => ({
  props: undefined as Record<string, unknown> | undefined,
}));

rs.mock("@/components/workspace/knowledge/eval-trend-chart", () => ({
  default: (props: Record<string, unknown>) => {
    canvasMock.props = props;
    return <div data-testid="eval-trend-chart-mock" />;
  },
}));

/** EvalRunDrawer mock（Task 6）：记录 props，open 时渲染占位。 */
const drawerMock = rs.hoisted(() => ({
  props: undefined as Record<string, unknown> | undefined,
}));

rs.mock("@/components/workspace/knowledge/eval-run-drawer", () => ({
  EvalRunDrawer: (props: Record<string, unknown>) => {
    drawerMock.props = props;
    return props.open ? <div data-testid="eval-run-drawer-mock" /> : null;
  },
}));

/** 题库视图 mock（Task 6）：记录 props（入口受控状态由常驻工具栏驱动），
 * 占位壳保持 testid，bank 自身契约在其专属测试文件。 */
const bankMock = rs.hoisted(() => ({
  props: undefined as Record<string, unknown> | undefined,
}));

rs.mock("@/components/workspace/knowledge/eval-question-bank", () => ({
  EvalQuestionBank: (props: Record<string, unknown>) => {
    bankMock.props = props;
    return <div data-testid="eval-questions-view" />;
  },
}));

/** 历史视图 mock（Task 7）：同上，history 契约在其专属测试文件。 */
rs.mock("@/components/workspace/knowledge/eval-run-history", () => ({
  EvalRunHistory: () => <div data-testid="eval-history-view" />,
}));

// jsdom 无 ResizeObserver——组件 resize 监听用空实现顶替（panels-shell 先例）。
class ResizeObserverStub {
  observe() {
    /* no-op stub */
  }
  unobserve() {
    /* no-op stub */
  }
  disconnect() {
    /* no-op stub */
  }
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??=
  ResizeObserverStub;

import { EvalTab } from "@/components/workspace/knowledge/eval-tab";
import { KB_TOASTER_ID } from "@/components/workspace/knowledge/kb-toast";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { overallFraction } from "@/core/knowledge/eval-run-status";
import type {
  EvalRunProgress,
  MetricsOverview,
  TrendResponse,
} from "@/core/knowledge/types";

const OVERVIEW: MetricsOverview = {
  kb_id: "kb-1",
  layer1: {
    run_id: "run-l1",
    created_at: "2026-08-20T09:00:00+00:00",
    metrics: {
      summary: {
        hit_rate: 0.928,
        recall_at_k: 0.897,
        mrr: 0.812,
        path_accuracy: 0.946,
        question_count: 20,
      },
      fact: {
        hit_rate: 0.952,
        recall_at_k: 0.923,
        mrr: 0.876,
        path_accuracy: 0.985,
        question_count: 12,
      },
    },
  },
  layer2: null,
};

const TREND: TrendResponse = {
  points: [
    {
      ts: "2026-08-20T09:00:00+00:00",
      recall_at_k: 0.9,
      hit_rate: 0.92,
      mrr: 0.81,
      path_accuracy: 0.95,
      faithfulness: 0.93,
      answer_relevancy: 0.87,
      context_precision: 0.85,
      citation_precision: 0.9,
      citation_recall: 0.85,
      seed_hit_rate: 0.8,
      routing_hit_rate: 0.87,
      run_id: "run-1",
      regression: null,
      is_baseline_update: false,
    },
  ],
  baseline: { recall_at_k: 0.9, threshold_percent: 3 },
  has_data: true,
  sparks: {
    faithfulness: [0.93],
    answer_relevancy: [0.87],
    context_precision: [0.85],
    context_recall: [],
    citation_precision: [0.9],
    citation_recall: [0.85],
    seed_hit_rate: [0.8],
    routing_hit_rate: [0.87],
  },
};

/** hook 返回形状的最小模拟：eval-tab 只消费 data/isLoading/error。 */
function queryState(overrides: {
  data?: unknown;
  isLoading?: boolean;
  error?: Error | null;
}) {
  return {
    data: overrides.data,
    isLoading: overrides.isLoading ?? false,
    error: overrides.error ?? null,
  };
}

function renderEvalTab(enabled = true) {
  return renderWithClient(<EvalTab enabled={enabled} kbId="kb-1" />);
}

function renderWithClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </I18nContext.Provider>,
  );
  return { ...view, queryClient };
}

describe("EvalTab 数据联通", () => {
  beforeEach(() => {
    canvasMock.props = undefined;
    drawerMock.props = undefined;
    hooksMock.useMetricsOverview.mockReset();
    hooksMock.useEvalTrend.mockReset();
    hooksMock.useEvalRuns.mockReset();
    hooksMock.useTriggerEvalRun.mockReset();
    // 缺省：查询就绪且有数据；历史空闲、无触发在途
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockImplementation(() =>
      queryState({ data: TREND }),
    );
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
    hooksMock.useCancelEvalRun.mockReset();
    hooksMock.useCancelEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("forwards kbId/enabled to all three data hooks (keep-alive lazy gating)", () => {
    renderEvalTab(true);
    expect(hooksMock.useMetricsOverview).toHaveBeenCalledWith("kb-1", true);
    expect(hooksMock.useEvalTrend).toHaveBeenCalledWith("kb-1", true);
    expect(hooksMock.useEvalRuns).toHaveBeenCalledWith("kb-1", true);

    cleanup();
    renderEvalTab(false);
    expect(hooksMock.useMetricsOverview).toHaveBeenLastCalledWith(
      "kb-1",
      false,
    );
    expect(hooksMock.useEvalTrend).toHaveBeenLastCalledWith(
      "kb-1",
      false,
    );
    expect(hooksMock.useEvalRuns).toHaveBeenLastCalledWith("kb-1", false);
  });

  it("renders overview table and trend chart shell on data", async () => {
    renderEvalTab();
    // 指标总览
    expect(screen.getByTestId("eval-layer1-table")).toBeTruthy();
    // 趋势卡片壳 + 视窗预设按钮组（内联档）
    expect(screen.getByText("指标趋势")).toBeTruthy();
    expect(screen.getByRole("radiogroup", { name: "时间窗口" })).toBeTruthy();
    // 趋势 canvas（dynamic 懒加载，mock 后异步落地）
    await screen.findByTestId("eval-trend-chart-mock");
    // props 透传：points/baseline/spanRequest + i18n labels 包
    expect(canvasMock.props?.points).toEqual(TREND.points);
    expect(canvasMock.props?.baseline).toEqual(TREND.baseline);
    // 默认预设 month（与旧 days_back=30 初始视野等价）+ 密度指示回调
    expect(canvasMock.props?.spanRequest).toEqual({ preset: "month", nonce: 0 });
    expect(typeof canvasMock.props?.onSpanChange).toBe("function");
    const labels = canvasMock.props?.labels as {
      recallAtK?: string;
      thresholdLabel?: (p: number) => string;
    };
    expect(labels.recallAtK).toBe("召回率@k");
    expect(labels.thresholdLabel?.(3)).toBe("回退阈值 -3%");
    // 阈值标注从线上文字退役（压数据线）→ 头部行红芯片（2026-09-05）。
    expect(screen.getByTestId("eval-threshold-chip").textContent).toBe("回退阈值 -3%");
  });

  it("趋势卡头 picker：默认空、开合出 5 个多选项、L2 项带‘仅完整档’尾注", async () => {
    renderEvalTab();
    await screen.findByTestId("eval-trend-chart-mock");
    // 会话级默认空选中透传给 chart
    expect(canvasMock.props?.pickerSelected).toEqual([]);

    fireEvent.keyDown(screen.getByTestId("eval-trend-picker"), { key: "ArrowDown" });
    const items = await screen.findAllByRole("menuitemcheckbox");
    expect(items).toHaveLength(5);
    // path_accuracy（L1）无尾注；引用三 + 路由命中率（L2）带‘仅完整档’
    expect(screen.getByRole("menuitemcheckbox", { name: /路径准确率/ }).textContent).not.toContain("仅完整档");
    expect(screen.getByRole("menuitemcheckbox", { name: /引用准确率/ }).textContent).toContain("仅完整档");
    expect(screen.getByRole("menuitemcheckbox", { name: /实体命中率/ }).textContent).toContain("仅完整档");
    expect(screen.getByRole("menuitemcheckbox", { name: /路由命中率/ }).textContent).toContain("仅完整档");
  });

  it("picker 勾选透传给 chart（pickerSelected），且会话级不跨挂载持久化", async () => {
    renderEvalTab();
    await screen.findByTestId("eval-trend-chart-mock");

    fireEvent.keyDown(screen.getByTestId("eval-trend-picker"), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: /引用准确率/ }));
    expect(canvasMock.props?.pickerSelected).toContain("citation_precision");

    // 重新挂载 → 回到空（useState 会话级，无 localStorage 持久化）
    cleanup();
    renderEvalTab();
    await screen.findByTestId("eval-trend-chart-mock");
    expect(canvasMock.props?.pickerSelected).toEqual([]);
  });

  it("legendselectchanged 回流：onLegendChange 更新 legendSelected 并回传 chart", async () => {
    renderEvalTab();
    await screen.findByTestId("eval-trend-chart-mock");

    // 模拟 echarts legendselectchanged：开启 MRR → 可见集变化经 state 回传给 chart
    // （y 轴自适应效果由 eval-trend-chart.unit.test.ts 的 buildChartOption 断言覆盖）。
    act(() => {
      (canvasMock.props?.onLegendChange as (s: Record<string, boolean>) => void)({
        "召回率@k": true,
        命中率: true,
        MRR: true,
        忠实度: false,
        相关性: false,
        精确率: false,
      });
    });
    expect(canvasMock.props?.legendSelected).toMatchObject({ MRR: true });
  });

  it("collapses the trend card from its header toggle (recall container vocabulary, 2026-09-05)", async () => {
    renderEvalTab();
    await screen.findByTestId("eval-trend-chart-mock");
    fireEvent.click(screen.getByTestId("eval-trend-toggle"));
    expect(screen.queryByTestId("eval-trend-chart-mock")).toBeNull();
    expect(screen.getByTestId("eval-trend-toggle").getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByTestId("eval-trend-toggle"));
    expect(await screen.findByTestId("eval-trend-chart-mock")).toBeTruthy();
  });

  it("横向下限沉进总览两卡：每卡独立横向滑块，总览块不再共用一个", () => {
    renderEvalTab();
    // 2026-08-28 修订（用户反馈）：下限从整列下沉到指标块——「谁有下限，谁自己滚」。
    // 2026-09-05 三迭代：下限与滑块再下沉一层——两张卡各自内部独立横滚。
    const scrollBlock = screen.getByTestId("eval-overview-scroll");
    // 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：Radix ScrollArea（type="scroll"、
    // 停 2s 淡出），不再原生 overflow-x-auto；min-w 下限隔了 Viewport 测量 div 一层，用选择器找。
    expect(scrollBlock.getAttribute("data-slot")).toBe("scroll-area");
    expect(scrollBlock.className).not.toContain("overflow-x-auto");
    // 每卡独立滑块：卡内 scroller 落地（本 fixture layer2=null 走空态分支，
    // 第二卡滑块归属/独立断言由 overview 专属测试覆盖）；总览块自身包装
    // 不再挂 min-w 下限（下限沉进卡内）。
    expect(screen.getByTestId("eval-layer1-scroll")).toBeTruthy();
    const outerWrapper = scrollBlock
      .querySelector("[data-slot='scroll-area-viewport']")
      ?.firstElementChild?.firstElementChild;
    expect(outerWrapper?.className).toContain("min-w-0");
    expect(outerWrapper?.className).not.toContain("min-w-[2");
    // 工具栏固定行，整 tab 无横向滚动；表头上方不画线（2026-09-02，与文档 tab 对齐）：
    // 表头自带吸顶发丝线，两条线夹表头的问题同款修复。
    expect(screen.getByTestId("eval-view-toolbar").className).toContain(
      "shrink-0",
    );
    expect(screen.getByTestId("eval-view-toolbar").className).not.toContain(
      "border-b",
    );
    expect(screen.getByTestId("eval-tab").className).not.toContain(
      "overflow-auto",
    );
  });

  it("loading 状态渲染加载提示而非空白", () => {
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ isLoading: true }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ isLoading: true }));
    renderEvalTab();
    expect(screen.getAllByText("加载中…").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("eval-layer1-table")).toBeNull();
    expect(screen.queryByTestId("eval-trend-chart-mock")).toBeNull();
  });

  it("错误状态渲染加载失败提示", () => {
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ error: new Error("boom") }),
    );
    hooksMock.useEvalTrend.mockReturnValue(
      queryState({ error: new Error("boom") }),
    );
    renderEvalTab();
    expect(screen.getAllByText("评测数据加载失败").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("eval-layer1-table")).toBeNull();
  });

  it("trend.has_data=false 渲染空态提示而非空白画布（新 KB 无评测历史）", async () => {
    hooksMock.useEvalTrend.mockReturnValue(
      queryState({
        data: { ...TREND, points: [], has_data: false, baseline: null },
      }),
    );
    renderEvalTab();
    expect(screen.getByText("暂无评测趋势数据")).toBeTruthy();
    expect(screen.queryByTestId("eval-trend-chart-mock")).toBeNull();
    // 给 dynamic import 一个兑现窗口，确认 canvas 不会被加载
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(canvasMock.props).toBeUndefined();
  });

  it("span preset click does not refetch; forwards spanRequest to the chart (contract v4)", () => {
    renderEvalTab();
    fireEvent.click(screen.getByRole("radio", { name: "周" }));
    // 服务端一次给 90d：useEvalTrend 无粒度维度（kbId, enabled）
    expect(hooksMock.useEvalTrend).toHaveBeenLastCalledWith("kb-1", true);
    // 点击请求经 spanRequest（nonce 递增）转发给 canvas 移视窗
    expect(canvasMock.props?.spanRequest).toEqual({ preset: "week", nonce: 1 });
  });

  it("clicking a trend point opens the run drawer; closing clears the run id", async () => {
    renderEvalTab();
    await screen.findByTestId("eval-trend-chart-mock");
    const onPointClick = canvasMock.props?.onPointClick as
      | ((runId: string) => void)
      | undefined;
    expect(onPointClick).toBeTypeOf("function");
    // 点击数据点 → drawer 打开并携带 runId（GET /eval-runs/{run_id} 由 drawer 内的
    // useEvalRun 发起，见 eval-run-drawer.dom.test.tsx）
    act(() => onPointClick?.("run-l1-1"));
    expect(screen.getByTestId("eval-run-drawer-mock")).toBeTruthy();
    expect(drawerMock.props?.runId).toBe("run-l1-1");
    expect(drawerMock.props?.open).toBe(true);
    expect(drawerMock.props?.kbId).toBe("kb-1");
    // 关闭 → 清空 runId，drawer 卸载
    act(() =>
      (drawerMock.props?.onOpenChange as (open: boolean) => void)(false),
    );
    await waitFor(() => {
      expect(screen.queryByTestId("eval-run-drawer-mock")).toBeNull();
    });
  });

  it("窄面板降档：容器溢出时粒度按钮组收进 ⋯ 菜单", async () => {
    // jsdom 无布局——把工具栏 scrollWidth 钉成大值模拟溢出（clientWidth 恒 0），
    // 对齐 vector-tab 测试先例。
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-trend-toolbar" ? 999 : 0;
      },
    });
    try {
      renderEvalTab();
      await screen.findByTestId("eval-trend-chart-mock");
      // 内联视窗预设按钮组消失，⋯ 按钮出现
      await waitFor(() => {
        expect(
          screen.queryByRole("radiogroup", { name: "时间窗口" }),
        ).toBeNull();
      });
      const more = screen.getByRole("button", { name: "更多选项" });
      // 菜单内承载视窗预设切换（Radix 键盘开菜单，vector-tab 先例）
      fireEvent.keyDown(more, { key: "ArrowDown" });
      fireEvent.click(await screen.findByRole("menuitemradio", { name: "月" }));
      expect(canvasMock.props?.spanRequest).toEqual({ preset: "month", nonce: 1 });
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });

  it("窄面板降档：阈值红芯片不渲染（spec 2026-09-24 §7.3 乙）", async () => {
    // 同款 scrollWidth 配方：tier 1 时芯片随宽档专属控件一起退场——图内虚线仍在，
    // 阈值信息在窄档的可读性代价已登记（spec §6.5，补救路 = 给虚线恢复数值标注）。
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-trend-toolbar" ? 999 : 0;
      },
    });
    try {
      renderEvalTab();
      await screen.findByTestId("eval-trend-chart-mock");
      await waitFor(() => {
        expect(screen.queryByTestId("eval-threshold-chip")).toBeNull();
      });
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });
});

// ── 二期工具栏与三视图（2026-08-27 spec §3/§5，plan Task 5）──────────────

const RUN_SUMMARY = {
  run_id: "run-latest",
  created_at: "2026-08-20T09:00:00+00:00",
  completed_at: null,
  environment: "local",
  status: "completed",
  is_baseline: false,
  has_layer1: true,
  has_layer2: false,
  regression_detected: false,
  langfuse_trace_url: null,
};

describe("EvalTab 三视图切换", () => {
  beforeEach(() => {
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ data: TREND }));
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
  });
  afterEach(() => cleanup());

  it("默认渲染总览视图（3 秒判断：健康度永远先看到）", () => {
    renderEvalTab();
    expect(screen.getByTestId("eval-layer1-table")).toBeTruthy();
    expect(screen.queryByTestId("eval-questions-view")).toBeNull();
    expect(screen.queryByTestId("eval-history-view")).toBeNull();
  });

  it("分段控件切换题库/历史视图（Task 6/7 填充前的占位壳）", () => {
    renderEvalTab();
    const group = screen.getByRole("radiogroup", { name: "评测视图切换" });
    expect(group).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    expect(screen.getByTestId("eval-questions-view")).toBeTruthy();
    // 管理型内容不与健康度总览抢首屏：切走后总览卸载
    expect(screen.queryByTestId("eval-layer1-table")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "历史" }));
    expect(screen.getByTestId("eval-history-view")).toBeTruthy();
    expect(screen.queryByTestId("eval-questions-view")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "总览" }));
    expect(screen.getByTestId("eval-layer1-table")).toBeTruthy();
  });
});

describe("EvalTab 常驻工具栏", () => {
  beforeEach(() => {
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ data: TREND }));
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
  });
  afterEach(() => cleanup());

  it("工具栏紧凑档：全栏按钮锁 h-7（44px，对齐文档/百科/向量/图谱工具栏基准），锁运行前后不跳动", () => {
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    const { rerender } = renderWithClient(<EvalTab enabled kbId="kb-1" />);
    const toolbar = screen.getByTestId("eval-view-toolbar");
    expect(toolbar.className).toContain("py-2");
    expect(
      within(toolbar).getByRole("button", { name: "快速评测" }).className,
    ).toContain("h-7");
    // 造题入口已收进档位下拉（2026-09-06）：工具栏内联不再出现。
    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    expect(
      within(toolbar).queryByRole("button", { name: /添加考题/ }),
    ).toBeNull();
    expect(
      within(toolbar).queryByRole("button", { name: /生成考题/ }),
    ).toBeNull();
    // 主按钮统一紧凑档（2026-08-30）：gap-1.5 + px-2.5（vector-tab chips 同款收窄），
    // 同内边距不跳宽；不降字号，保住主动词视觉权重。
    const runButton = within(toolbar).getByRole("button", { name: "快速评测" });
    expect(runButton.className).toContain("px-2.5");
    expect(runButton.className).toContain("gap-1.5");

    // 锁运行（in_flight=true）：按钮同一 h-7 档，工具栏高度不变
    act(() => {
      hooksMock.useEvalRuns.mockReturnValue(
        queryState({
          data: { in_flight: true, runs: [RUN_SUMMARY], total: 1 },
        }),
      );
      rerender(
        <I18nContext.Provider
          value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
        >
          <QueryClientProvider
            client={
              new QueryClient({ defaultOptions: { queries: { retry: false } } })
            }
          >
            <EvalTab enabled kbId="kb-1" />
          </QueryClientProvider>
        </I18nContext.Provider>,
      );
    });
    expect(
      within(toolbar).getByRole("button", { name: "检索评测" }).className,
    ).toContain("h-7");
  });

  it("视图分段控件保持底色块样式（与顶部知识库大 tab 的下划线样式做层级区分）", () => {
    renderEvalTab();
    const group = screen.getByRole("radiogroup", { name: "评测视图切换" });
    expect(group.className).toContain("bg-muted");
    const selected = within(group).getByRole("radio", { name: "总览" });
    expect(selected.getAttribute("aria-checked")).toBe("true");
    expect(selected.className).toContain("bg-background");
  });

  it("in_flight=true 时按钮转运行态禁用（无 progress → 降级「检索评测」）", () => {
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: true, runs: [], total: 0 } }),
    );
    renderEvalTab();
    const runButton = screen.getByRole("button", { name: "检索评测" });
    expect(runButton.hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: "快速评测" })).toBeNull();
  });

  it("mutation pending 同样呈现运行态禁用（点击→首次轮询间隙）", () => {
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: true,
    });
    renderEvalTab();
    expect(
      screen.getByRole("button", { name: "检索评测" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("点击运行 → enqueued 成功 toast", () => {
    const mutate = rs.fn(
      (
        _vars: unknown,
        opts?: { onSuccess?: (r: { status: string }) => void },
      ) => {
        opts?.onSuccess?.({ status: "enqueued" });
      },
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    expect(mutate).toHaveBeenCalled();
    expect(
      rs.mocked(toast.success).mock.calls.some(([m]) => m === "评测已开始"),
    ).toBe(true);
  });

  it("enqueued → 乐观置位缓存 in_flight=true（轮询自锁修复，无需切视图）", () => {
    const mutate = rs.fn(
      (
        _vars: unknown,
        opts?: { onSuccess?: (r: { status: string }) => void },
      ) => {
        opts?.onSuccess?.({ status: "enqueued" });
      },
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    const { queryClient } = renderWithClient(<EvalTab enabled kbId="kb-1" />);
    // 首查已回空闲 payload：不乐观置位则 refetchInterval 永不启动（自锁根因）。
    const runsKey = ["knowledge-bases", "kb-1", "eval-runs", "history"];
    queryClient.setQueryData(runsKey, {
      in_flight: false,
      runs: [],
      total: 0,
    });

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    const cached = queryClient.getQueryData<{ in_flight: boolean }>(runsKey);
    expect(cached?.in_flight).toBe(true);
  });

  it("enqueued 但无缓存 → 乐观创建 in_flight 条目（不退化 invalidate，绕开后端竞态）", () => {
    const mutate = rs.fn(
      (
        _vars: unknown,
        opts?: { onSuccess?: (r: { status: string }) => void },
      ) => {
        opts?.onSuccess?.({ status: "enqueued" });
      },
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    // 显式置 idle，保证「运行评测」按钮可点（本 describe 的 useEvalRuns 为 sticky）。
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    const { queryClient } = renderWithClient(<EvalTab enabled kbId="kb-1" />);
    const invalidateSpy = rs.fn().mockResolvedValue(undefined);
    queryClient.invalidateQueries =
      invalidateSpy as typeof queryClient.invalidateQueries;
    const runsKey = ["knowledge-bases", "kb-1", "eval-runs", "history"];
    // 前置：useEvalRuns 被 mock，真实 queryClient 里该 key 尚无缓存（空缓存路径）。
    expect(queryClient.getQueryData(runsKey)).toBeUndefined();

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    // 乐观**创建**最小条目：in_flight=true、3s 轮询立即接管；不退化 invalidate
    // （旧写法空缓存时 refetch 会撞后端 create_task 延迟自增 _IN_FLIGHT 的竞态）。
    const cached = queryClient.getQueryData<{
      in_flight: boolean;
      runs: unknown[];
      total: number;
    }>(runsKey);
    expect(cached?.in_flight).toBe(true);
    expect(cached?.runs).toEqual([]);
    expect(cached?.total).toBe(0);
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  /** 进度快照夹具：冷启动（无实测、无 phase_started_at）→ 条几何落在先验 10/35/55。 */
  function liveProgress(
    overrides: Partial<EvalRunProgress> = {},
  ): EvalRunProgress {
    return {
      run_id: "run-live",
      phase: "questions",
      done: 3,
      total: 10,
      failed: 0,
      started_at: "2026-09-06T10:00:00+00:00",
      updated_at: "2026-09-06T10:05:00+00:00",
      phase_durations: {},
      tail: { kind: "item", phase: "questions", done: 3, total: 10, failed: 0 },
      ...overrides,
    };
  }

  function mockRunning(snapshot?: EvalRunProgress | null) {
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({
        data: {
          in_flight: true,
          progress: snapshot ?? undefined,
          runs: [],
          total: 0,
        },
      }),
    );
  }

  const barPercent = (
    snapshot: EvalRunProgress | null,
    tier: "l1" | "l1_l2" = "l1_l2",
  ) => `${Math.round(overallFraction(snapshot, tier) * 100)}%`;

  it("questions 段进度 → 按钮「答题评测 2/3」+ 总览容器承载加权条与单行日志", () => {
    const snapshot = liveProgress({
      failed: 1,
      tail: { kind: "item", phase: "questions", done: 3, total: 10, failed: 1 },
    });
    mockRunning(snapshot);
    renderEvalTab();

    // 按钮仍是紧凑表面：4 字阶段名 + n/3。
    expect(
      screen.getByRole("button", { name: "答题评测 2/3" }),
    ).toBeTruthy();

    // 容器（总览检索质量卡上方）：加权条 + 刻线 + 当前段跨度 + 日志 + 失败徽标。
    const banner = screen.getByTestId("eval-run-banner");
    const bar = within(banner).getByRole("progressbar");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.getAttribute("aria-valuenow")).toBe(
      String(Math.round(overallFraction(snapshot, "l1_l2") * 100)),
    );
    expect(screen.getByTestId("eval-banner-fill").style.width).toBe(
      barPercent(snapshot),
    );
    expect(
      screen.getAllByTestId("eval-banner-tick").map((tick) => tick.style.left),
    ).toEqual(["10%", "45%"]);
    expect(screen.getByTestId("eval-banner-span").style.left).toBe("10%");
    const log = screen.getByTestId("eval-banner-log");
    expect(log.textContent).toContain("答题评测 3/10");
    expect(log.textContent).toContain("失败 1");
    // 底缘细线已退役（只表征 questions 段的"假进度条"，用户定案直接删）。
    expect(screen.queryByTestId("eval-run-progress")).toBeNull();
  });

  it("layer1 段（快速档）→ 按钮「检索评测」不显计数 + 容器单段无刻线", () => {
    mockRunning(
      liveProgress({
        phase: "layer1",
        done: 0,
        total: 1,
        tail: { kind: "phase", phase: "layer1", done: 0, total: 1, failed: 0 },
      }),
    );
    renderEvalTab();

    expect(screen.getByRole("button", { name: "检索评测" })).toBeTruthy();
    expect(screen.queryAllByTestId("eval-banner-tick")).toHaveLength(0);
    expect(screen.getByTestId("eval-banner-span").style.width).toBe("100%");
    expect(screen.getByTestId("eval-banner-fill").style.width).toBe(
      barPercent(liveProgress({ phase: "layer1", done: 0, total: 1 }), "l1"),
    );
    expect(screen.getByTestId("eval-banner-log").textContent).toContain(
      "进入检索评测",
    );
  });

  it("ragas 段进度 → 按钮「质量评估 3/3」+ 容器条已跨过前两段", () => {
    const snapshot = liveProgress({
      phase: "ragas",
      done: 12,
      total: 20,
      tail: { kind: "item", phase: "ragas", done: 12, total: 20, failed: 0 },
    });
    mockRunning(snapshot);
    renderEvalTab();

    expect(screen.getByRole("button", { name: "质量评估 3/3" })).toBeTruthy();
    // 在飞的 run 已离开 layer1 → 必属完整档（即使单选停在快速档）：三段几何。
    expect(screen.getAllByTestId("eval-banner-tick")).toHaveLength(2);
    // 第三段起点 = 前两段先验权重和（45%）。
    expect(screen.getByTestId("eval-banner-span").style.left).toBe("45%");
    expect(screen.getByTestId("eval-banner-fill").style.width).toBe(
      barPercent(snapshot),
    );
    expect(screen.getByTestId("eval-banner-log").textContent).toContain(
      "质量评估 12/20",
    );
  });

  it("运行中但无 progress（首个轮询未到）→ 容器渲染空条与等待行", () => {
    mockRunning(null);
    renderEvalTab();

    expect(screen.getByTestId("eval-run-banner")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "0",
    );
    expect(screen.getByTestId("eval-banner-fill").style.width).toBe("0%");
    expect(screen.getByTestId("eval-banner-eta").textContent).toBe("估算中…");
    expect(screen.getByTestId("eval-banner-log").textContent).toContain(
      "等待首个进度事件",
    );
  });

  it("容器只在总览：题库/历史视图靠按钮阶段名承载", () => {
    mockRunning(liveProgress());
    renderEvalTab();
    expect(screen.getByTestId("eval-run-banner")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    expect(screen.queryByTestId("eval-run-banner")).toBeNull();
    expect(
      screen.getByRole("button", { name: "答题评测 2/3" }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "总览" }));
    expect(screen.getByTestId("eval-run-banner")).toBeTruthy();
  });

  it("空闲有历史 → 常驻槽显上次评测摘要（spec §10）", () => {
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({
        data: {
          in_flight: false,
          progress: null,
          runs: [
            {
              run_id: "run-last",
              created_at: new Date(Date.now() - 60_000).toISOString(),
              completed_at: new Date(Date.now() - 30_000).toISOString(),
              environment: "local",
              status: "completed",
              is_baseline: false,
              has_layer1: true,
              has_layer2: true,
              regression_detected: false,
              langfuse_trace_url: null,
            },
          ],
          total: 1,
        },
      }),
    );
    renderEvalTab();

    // has_layer2 → 完整档；30s 耗时 → 「30s」（单位 s，无前缀）。
    expect(screen.getByTestId("eval-run-banner").textContent).toContain(
      "完整评测 · 耗时 30s",
    );
  });

  it("空闲无历史 → 常驻槽显尚未评测行", () => {
    // 本 describe 的 beforeEach 不重置 useEvalRuns（靠各用例 sticky 设值），故本例
    // 必须显式置 idle；也因为它排在末位，后续用例才不会继承 in_flight:true。
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    renderEvalTab();

    // 槽常驻（spec §10）：空闲态容器也在，只是内容换成 muted 单行；细线已退役。
    const slot = screen.getByTestId("eval-run-banner");
    expect(slot.textContent).toContain("尚未评测");
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByTestId("eval-run-progress")).toBeNull();
  });

  it("already_running → 提示 toast，不报错", () => {
    const mutate = rs.fn(
      (
        _vars: unknown,
        opts?: { onSuccess?: (r: { status: string }) => void },
      ) => {
        opts?.onSuccess?.({ status: "already_running" });
      },
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    expect(
      rs.mocked(toast.info).mock.calls.some(([m]) => m === "已有评测正在运行"),
    ).toBe(true);
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();
  });

  it("触发失败 → 错误 toast", () => {
    const mutate = rs.fn((_vars: unknown, opts?: { onError?: () => void }) => {
      opts?.onError?.();
    });
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    expect(
      rs.mocked(toast.error).mock.calls.some(([m]) => m === "评测触发失败"),
    ).toBe(true);
  });

  it("drain 边：in_flight true→false 一次性失效三个评测 query", () => {
    let runsState = queryState({
      data: { in_flight: true, runs: [], total: 0 },
    });
    hooksMock.useEvalRuns.mockImplementation(() => runsState);
    const { queryClient, rerender } = renderWithClient(
      <EvalTab enabled kbId="kb-1" />,
    );
    const invalidateSpy = rs.fn().mockResolvedValue(undefined);
    queryClient.invalidateQueries =
      invalidateSpy as typeof queryClient.invalidateQueries;

    // 初始挂载（含 in_flight=true 首见）不触发失效
    expect(invalidateSpy).not.toHaveBeenCalled();

    act(() => {
      runsState = queryState({
        data: { in_flight: false, runs: [], total: 0 },
      });
      rerender(
        <I18nContext.Provider
          value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
        >
          <QueryClientProvider client={queryClient}>
            <EvalTab enabled kbId="kb-1" />
          </QueryClientProvider>
        </I18nContext.Provider>,
      );
    });

    const keys = invalidateSpy.mock.calls.map(
      ([arg]) => (arg as { queryKey: readonly unknown[] }).queryKey,
    );
    expect(keys).toContainEqual([
      "knowledge-bases",
      "kb-1",
      "eval-runs",
      "history",
    ]);
    expect(keys).toContainEqual([
      "knowledge-bases",
      "kb-1",
      "eval-runs",
      "latest",
    ]);
    expect(keys).toContainEqual([
      "knowledge-bases",
      "kb-1",
      "eval-runs",
      "trend",
    ]);
  });

  it("内容区边距：总览 px-4 py-3 滚动容器；题库高度有界 flex 列；历史独立 ScrollArea 同题库表", () => {
    renderEvalTab();
    const content = screen.getByTestId("eval-view-content");
    expect(content.className).toContain("px-4");
    // 内容区同为百科 Tab 容器同款 overlay 滚动条（2026-09-04），不再原生 overflow-auto。
    expect(content.getAttribute("data-slot")).toBe("scroll-area");
    expect(content.className).not.toContain("overflow-auto");

    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    // 题库视图退役外层 ScrollArea（2026-09-07 底部停靠重设计）：高度有界
    // flex 列——表格区与底部审核容器按比例分高，纵/横滚沉进表格区自身
    // overflow 容器（吸顶表头滚动祖先行为同原生容器）。
    expect(screen.queryByTestId("eval-view-content")).toBeNull();
    const questionsContent = screen.getByTestId("eval-questions-content");
    expect(questionsContent.className).toContain("flex-1");
    expect(questionsContent.className).toContain("min-h-0");

    fireEvent.click(screen.getByRole("radio", { name: "历史" }));
    // 历史视图（2026-09-08 三轮）：独立 ScrollArea 与题库表同容器语境
    // （无横内边距→表格贴面板边），退役共享总览容器的 px-4。
    expect(screen.queryByTestId("eval-view-content")).toBeNull();
    const historyContent = screen.getByTestId("eval-history-content");
    expect(historyContent.className).not.toContain("px-4");
    expect(historyContent.getAttribute("data-slot")).toBe("scroll-area");
  });

  it("窄面板降档：视图工具栏溢出时运行按钮收进 ⋯ 菜单", async () => {
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-view-toolbar" ? 999 : 0;
      },
    });
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    try {
      const mutate = rs.fn();
      hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
      renderEvalTab();
      await screen.findByTestId("eval-trend-chart-mock");
      // 内联运行按钮消失，视图工具栏自己的 ⋯ 按钮出现（趋势工具栏不受影响）
      await waitFor(() => {
        expect(
          within(screen.getByTestId("eval-view-toolbar")).queryByRole(
            "button",
            { name: "快速评测" },
          ),
        ).toBeNull();
      });
      const more = within(screen.getByTestId("eval-view-toolbar")).getByRole(
        "button",
        { name: "更多选项" },
      );
      fireEvent.keyDown(more, { key: "ArrowDown" });
      fireEvent.click(
        await screen.findByRole("menuitem", { name: "快速评测" }),
      );
      expect(mutate).toHaveBeenCalled();
      // 分段控件恒内联：三视图标签足够短
      expect(
        screen.getByRole("radiogroup", { name: "评测视图切换" }),
      ).toBeTruthy();
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });

  it("tier 1 ⋯ 触发器与内联按钮同档（28px），切题库降档时工具栏不跳高", async () => {
    // 复现路径（2026-08-30 用户报告）：总览无溢出（44px）→ 切题库三按钮溢出升档，
    // 若 ⋯ 触发器是 size=sm（h-8=32px），栏高 44→48 突跳；锁 size-7 与 h-7 同档。
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-view-toolbar" ? 999 : 0;
      },
    });
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    try {
      renderEvalTab();
      fireEvent.click(screen.getByRole("radio", { name: "题库" }));
      await waitFor(() => {
        expect(
          within(screen.getByTestId("eval-view-toolbar")).queryByRole(
            "button",
            { name: "快速评测" },
          ),
        ).toBeNull();
      });
      const more = within(screen.getByTestId("eval-view-toolbar")).getByRole(
        "button",
        { name: "更多选项" },
      );
      expect(more.className).toContain("size-7");
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });

  it("tier 1 时状态文案让位（次要信息先收缩，分段控件与 ⋯ 恒在）", () => {
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-view-toolbar" ? 999 : 0;
      },
    });
    try {
      renderEvalTab();
      // 状态文案已整体移除（2026-08-28 反馈）；tier 1 只保留分段控件 + ⋯
      expect(screen.queryByText("尚未运行")).toBeNull();
      expect(
        screen.getByRole("radiogroup", { name: "评测视图切换" }),
      ).toBeTruthy();
      expect(
        within(screen.getByTestId("eval-view-toolbar")).getByRole("button", {
          name: "更多选项",
        }),
      ).toBeTruthy();
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });
});

// ── 题库造题入口并入常驻工具栏（2026-08-29 UX 修订）────────────────────────
// 两条工具栏叠加 + 添加入口沉底的双重回退：入口提升到常驻工具栏右侧，
// 仅题库视图出现；状态提升到 EvalTab，bank 的 dialog 改受控。

describe("EvalTab 题库入口（常驻工具栏）", () => {
  beforeEach(() => {
    bankMock.props = undefined;
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ data: TREND }));
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
  });
  afterEach(() => cleanup());

  it("造题入口仅题库视图出现在档位下拉，主按钮保持最右主位", async () => {
    renderEvalTab();
    const openTierMenu = () =>
      fireEvent.keyDown(screen.getByRole("button", { name: "评测档位" }), {
        key: "ArrowDown",
      });
    // 总览视图：下拉内不出现造题入口（视图相关，不常驻）。
    openTierMenu();
    expect(screen.queryByRole("menuitem", { name: /添加考题/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /生成考题/ })).toBeNull();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    openTierMenu();
    expect(screen.getByRole("menuitem", { name: /添加考题/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /生成考题/ })).toBeTruthy();
    // 分割线隔离档位单选与造题入口。
    expect(screen.getAllByRole("separator")).toHaveLength(1);
    // 菜单打开时 Radix 将背景 aria-hidden，需先关闭再查内联主按钮。
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    // 主按钮仍在工具栏内联最右主位。
    expect(
      within(screen.getByTestId("eval-view-toolbar")).getByRole("button", {
        name: "快速评测",
      }),
    ).toBeTruthy();

    // 切走即消失（历史无造题语义）。
    fireEvent.click(screen.getByRole("radio", { name: "历史" }));
    openTierMenu();
    expect(screen.queryByRole("menuitem", { name: /添加考题/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /生成考题/ })).toBeNull();
  });

  it("下拉「从文档生成考题」→ bank 受控 synthesisOpen 置真，回调可复位", async () => {
    renderEvalTab();
    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    expect(bankMock.props?.synthesisOpen).toBe(false);
    fireEvent.keyDown(screen.getByRole("button", { name: "评测档位" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: /生成考题/ }));
    expect(bankMock.props?.synthesisOpen).toBe(true);
    act(() =>
      (bankMock.props?.onSynthesisOpenChange as (open: boolean) => void)(false),
    );
    expect(bankMock.props?.synthesisOpen).toBe(false);
  });

  it("下拉「添加考题」→ bank 受控 addOpen 置真", async () => {
    renderEvalTab();
    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    expect(bankMock.props?.addOpen).toBe(false);
    fireEvent.keyDown(screen.getByRole("button", { name: "评测档位" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: /添加考题/ }));
    expect(bankMock.props?.addOpen).toBe(true);
  });

  it("窄面板降档：题库动作与运行评测一并收进 ⋯ 菜单", async () => {
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-view-toolbar" ? 999 : 0;
      },
    });
    try {
      renderEvalTab();
      fireEvent.click(screen.getByRole("radio", { name: "题库" }));
      // 内联按钮消失，⋯ 菜单承载三个动作（两造题入口 + 运行评测）
      await waitFor(() => {
        expect(
          within(screen.getByTestId("eval-view-toolbar")).queryByRole(
            "button",
            { name: /生成考题/ },
          ),
        ).toBeNull();
      });
      const more = within(screen.getByTestId("eval-view-toolbar")).getByRole(
        "button",
        { name: "更多选项" },
      );
      fireEvent.keyDown(more, { key: "ArrowDown" });
      // 降档不丢图标（2026-09-02）：⋯ 菜单逐项携图标，与内联按钮/题库行三点
      // 同一图标语汇（Plus / Sparkles / Play / Layers）。
      const items = await screen.findAllByRole("menuitem");
      expect(items.map((item) => item.textContent)).toEqual([
        "添加考题",
        "生成考题",
        "快速评测",
        "完整评测",
      ]);
      expect(items.every((item) => item.querySelector("svg") !== null)).toBe(
        true,
      );
      fireEvent.click(screen.getByRole("menuitem", { name: /生成考题/ }));
      expect(bankMock.props?.synthesisOpen).toBe(true);
      fireEvent.keyDown(more, { key: "ArrowDown" });
      fireEvent.click(
        await screen.findByRole("menuitem", { name: /添加考题/ }),
      );
      expect(bankMock.props?.addOpen).toBe(true);
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });
});

// ── 题库搜索常驻工具栏（2026-08-30）──────────────────────────────
// 定案（用户拍板）：不做展开/收起交互，搜索框常驻在分段控件与动作按钮之间，
// 仅题库视图出现；纯前端过滤，状态在本层，经 searchQuery prop 下发给 bank。

describe("EvalTab 题库搜索（常驻工具栏）", () => {
  beforeEach(() => {
    bankMock.props = undefined;
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ data: TREND }));
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
  });
  afterEach(() => cleanup());

  it("搜索框仅题库视图出现，与工具栏同档（h-7）", () => {
    renderEvalTab();
    expect(screen.queryByPlaceholderText("搜索问题…")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    const input = screen.getByPlaceholderText("搜索问题…");
    expect(input.className).toContain("h-7");
    // 搜索最小宽 160px（2026-08-30）：输入型控件的可用底线，窄了宁可让按钮走 ⋯ 降档。
    expect(input.parentElement!.className).toContain("min-w-40");

    fireEvent.click(screen.getByRole("radio", { name: "历史" }));
    expect(screen.queryByPlaceholderText("搜索问题…")).toBeNull();
  });

  it("输入透传 bank 受控 searchQuery；✕ 清除按钮只在有内容时出现", () => {
    renderEvalTab();
    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    expect(bankMock.props?.searchQuery).toBe("");
    expect(screen.queryByRole("button", { name: "清空搜索" })).toBeNull();

    fireEvent.change(screen.getByPlaceholderText("搜索问题…"), {
      target: { value: "多态" },
    });
    expect(bankMock.props?.searchQuery).toBe("多态");
    fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
    expect(bankMock.props?.searchQuery).toBe("");
    expect(screen.queryByRole("button", { name: "清空搜索" })).toBeNull();
  });

  it("窄面板降档：按钮收进 ⋯，搜索框保留（只收按钮不收搜索）", async () => {
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-view-toolbar" ? 999 : 0;
      },
    });
    try {
      renderEvalTab();
      fireEvent.click(screen.getByRole("radio", { name: "题库" }));
      await waitFor(() => {
        expect(
          within(screen.getByTestId("eval-view-toolbar")).queryByRole(
            "button",
            { name: "快速评测" },
          ),
        ).toBeNull();
      });
      expect(screen.getByPlaceholderText("搜索问题…")).toBeTruthy();
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });
});

// ── 运行评测分档（2026-09-01 B 方案 Task 4）────────────────────
// 分体按钮：主键一键 L1 全量（高频习惯不变），右侧箭头下拉选「完整评测」，
// 完整档弹确认对话框（成本提示）；窄面板降档时完整评测项并入 ⋯ 菜单。
// 档位后缀 (L1+L2) 已从菜单文案移除（2026-09-02），与快速档四字等长对齐。

describe("EvalTab 运行评测分档（B 方案）", () => {
  beforeEach(() => {
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ data: TREND }));
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
  });
  afterEach(() => cleanup());

  it("主按钮一键跑 L1 快速档（payload layers=l1）", () => {
    const mutate = rs.fn();
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    expect(mutate).toHaveBeenCalled();
    expect(mutate.mock.calls[0]?.[0]).toEqual({ layers: "l1" });
  });

  it("箭头下拉含完整评测项：确认后以 layers=l1_l2 触发", async () => {
    const mutate = rs.fn();
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();

    const chevron = screen.getByRole("button", { name: "评测档位" });
    fireEvent.keyDown(chevron, { key: "ArrowDown" });
    // 下拉为互斥单选（2026-09-06）：点「完整评测」只勾选不运行，主按钮随即改显该档名。
    fireEvent.click(await screen.findByRole("menuitem", { name: "完整评测" }));
    expect(screen.getByRole("button", { name: "完整评测" })).toBeTruthy();

    // 主按钮执行勾中档 → 确认对话框（成本+范围说明在场）→ 确认后触发完整档。
    fireEvent.click(screen.getByRole("button", { name: "完整评测" }));
    expect(await screen.findByText("运行完整评测")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "开始完整评测" }));
    expect(mutate).toHaveBeenCalled();
    expect(mutate.mock.calls[0]?.[0]).toEqual({ layers: "l1_l2" });
  });

  it("完整档触发后 layer1 段 → 按钮「检索评测 1/3」（tier 单选驱动计数）", async () => {
    let runsState = queryState({
      data: { in_flight: false, runs: [], total: 0 },
    });
    hooksMock.useEvalRuns.mockImplementation(() => runsState);
    const mutate = rs.fn(
      (
        _vars: unknown,
        opts?: { onSuccess?: (r: { status: string }) => void },
      ) => {
        opts?.onSuccess?.({ status: "enqueued" });
      },
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    const { queryClient, rerender } = renderEvalTab();

    // 驱动完整评测：chevron 勾选「完整评测」→ 主按钮（改显完整评测）→ 对话框
    // 「开始完整评测」→ l1_l2 触发；tier=l1_l2 驱动 layer1 显 n/3 计数。
    const chevron = screen.getByRole("button", { name: "评测档位" });
    fireEvent.keyDown(chevron, { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "完整评测" }));
    fireEvent.click(screen.getByRole("button", { name: "完整评测" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "开始完整评测" }),
    );
    expect(mutate.mock.calls[0]?.[0]).toEqual({ layers: "l1_l2" });

    // 模拟轮询回填 in_flight（layer1 段，progress 尚未到）：完整档显 n/3 计数，
    // 与快速档 layer1 只显「检索评测」区分开。
    act(() => {
      runsState = queryState({
        data: { in_flight: true, runs: [], total: 0 },
      });
      rerender(
        <I18nContext.Provider
          value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
        >
          <QueryClientProvider client={queryClient}>
            <EvalTab enabled kbId="kb-1" />
          </QueryClientProvider>
        </I18nContext.Provider>,
      );
    });

    expect(
      screen.getByRole("button", { name: "检索评测 1/3" }),
    ).toBeTruthy();
  });

  it("确认对话框取消不触发", async () => {
    const mutate = rs.fn();
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();

    const chevron = screen.getByRole("button", { name: "评测档位" });
    fireEvent.keyDown(chevron, { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "完整评测" }));
    fireEvent.click(screen.getByRole("button", { name: "完整评测" }));
    fireEvent.click(await screen.findByRole("button", { name: "取消" }));
    expect(mutate).not.toHaveBeenCalled();
  });

  it("运行中箭头下拉让位给终止按钮（spec §11 次槽 morph，2026-09-06）", () => {
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: true,
    });
    renderEvalTab();
    // 旧契约是 chevron 与主按钮一并禁用；新契约：运行态次槽 morph 为终止按钮，
    // 档位下拉（只对下一次运行有意义）不在。
    expect(screen.queryByRole("button", { name: "评测档位" })).toBeNull();
    expect(screen.getByTestId("eval-cancel-button")).toBeTruthy();
  });

  it("窄面板降档：箭头收进 ⋯，完整评测项并入菜单", async () => {
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-view-toolbar" ? 999 : 0;
      },
    });
    const mutate = rs.fn();
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    try {
      renderEvalTab();
      await waitFor(() => {
        expect(
          within(screen.getByTestId("eval-view-toolbar")).queryByRole(
            "button",
            { name: "评测档位" },
          ),
        ).toBeNull();
      });
      const more = within(screen.getByTestId("eval-view-toolbar")).getByRole(
        "button",
        { name: "更多选项" },
      );
      fireEvent.keyDown(more, { key: "ArrowDown" });
      fireEvent.click(
        await screen.findByRole("menuitem", { name: "完整评测" }),
      );
      expect(await screen.findByText("运行完整评测")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "开始完整评测" }));
      expect(mutate.mock.calls[0]?.[0]).toEqual({ layers: "l1_l2" });
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });
});

// ── 选题运行工具栏原位切换（2026-09-02 批量运行栏退役）────────
// 选题集上提 eval-tab：题库视图有选中时运行主键切「快速评测」、完整档
// 携 question_ids；触发成功清空选择；选中集不泄漏到总览/历史视图。

describe("EvalTab 选题运行工具栏原位切换", () => {
  beforeEach(() => {
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ data: TREND }));
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
  });
  afterEach(() => cleanup());

  function selectQuestions(ids: string[]) {
    // bank mock 上报选中集（模拟 bank 内勾选/右键选中）。
    act(() => {
      (
        bankMock.props?.onSelectedIdsChange as (
          next: ReadonlySet<string>,
        ) => void
      )(new Set(ids));
    });
  }

  it("题库视图选中题目不改变主按钮档位名，触发携 question_ids 并清空选择", async () => {
    const mutate = rs.fn(
      (
        _input: unknown,
        opts?: { onSuccess?: (response: { status: string }) => void },
      ) => {
        opts?.onSuccess?.({ status: "enqueued" });
      },
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();
    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    const toolbar = screen.getByTestId("eval-view-toolbar");
    // 档位单选重设计（2026-09-06）：主按钮恒显勾中档位名，选中题目不变脸。
    expect(
      within(toolbar).getByRole("button", { name: "快速评测" }),
    ).toBeTruthy();
    selectQuestions(["q_1", "q_2"]);
    expect(
      within(toolbar).getByRole("button", { name: "快速评测" }),
    ).toBeTruthy();

    fireEvent.click(within(toolbar).getByRole("button", { name: "快速评测" }));
    // 范围静默携入 payload（按钮不附加后缀）。
    expect(mutate.mock.calls[0]?.[0]).toEqual({
      layers: "l1",
      question_ids: ["q_1", "q_2"],
    });
    // 触发成功清空选题集（原批量栏语义承接）。
    await waitFor(() => {
      expect((bankMock.props?.selectedIds as ReadonlySet<string>).size).toBe(0);
    });
  });

  it("选中态完整评测档：确认后携 layers=l1_l2 与 question_ids", async () => {
    const mutate = rs.fn();
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();
    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    selectQuestions(["q_9"]);

    const chevron = screen.getByRole("button", { name: "评测档位" });
    fireEvent.keyDown(chevron, { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "完整评测" }));
    // 主按钮执行勾中档 → 确认弹窗标明范围（所选 1 题）→ 确认携 question_ids。
    fireEvent.click(screen.getByRole("button", { name: "完整评测" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("运行范围：所选 1 题。");
    fireEvent.click(screen.getByRole("button", { name: "开始完整评测" }));
    expect(mutate.mock.calls[0]?.[0]).toEqual({
      layers: "l1_l2",
      question_ids: ["q_9"],
    });
  });

  it("选题集跨视图不泄漏：总览视图主键仍是全量运行", () => {
    const mutate = rs.fn(
      (
        _input: unknown,
        opts?: { onSuccess?: (response: { status: string }) => void },
      ) => {
        opts?.onSuccess?.({ status: "enqueued" });
      },
    );
    hooksMock.useTriggerEvalRun.mockReturnValue({ mutate, isPending: false });
    renderEvalTab();
    fireEvent.click(screen.getByRole("radio", { name: "题库" }));
    selectQuestions(["q_1"]);
    fireEvent.click(screen.getByRole("radio", { name: "总览" }));
    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));
    expect(mutate.mock.calls[0]?.[0]).toEqual({ layers: "l1" });
  });
});

// ── 终止评测（spec 2026-09-06 §11 Task 20）──────────────────────
// 运行态分体按钮次槽 morph 为终止按钮（chevron 档位下拉运行中本就 disabled
// 且无意义）；两步 inline 确认：首击变「确认终止?」（3s 回退），再击才发；
// 窄档（⋯ 菜单）同样可达；槽 running 态不加控件（§9 冻结保持绝对）。

describe("EvalTab 终止评测（spec §11）", () => {
  beforeEach(() => {
    hooksMock.useMetricsOverview.mockReturnValue(
      queryState({ data: OVERVIEW }),
    );
    hooksMock.useEvalTrend.mockReturnValue(queryState({ data: TREND }));
    hooksMock.useTriggerEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
    hooksMock.useCancelEvalRun.mockReturnValue({
      mutate: rs.fn(),
      isPending: false,
    });
  });
  afterEach(() => {
    cleanup();
    rs.useRealTimers();
  });

  function mockRunning() {
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: true, runs: [], total: 0 } }),
    );
  }

  it("运行态次槽 morph 为终止按钮（chevron 档位下拉不在）", () => {
    mockRunning();
    renderEvalTab();
    const toolbar = screen.getByTestId("eval-view-toolbar");
    expect(within(toolbar).getByTestId("eval-cancel-button")).toBeTruthy();
    expect(
      within(toolbar).queryByRole("button", { name: "评测档位" }),
    ).toBeNull();
  });

  it("两步 inline 确认：首击变「确认终止?」不发，再击才发 + 成功 toast", () => {
    const mutate = rs.fn(
      (_input: unknown, opts?: { onSuccess?: () => void }) => {
        opts?.onSuccess?.();
      },
    );
    hooksMock.useCancelEvalRun.mockReturnValue({ mutate, isPending: false });
    mockRunning();
    renderEvalTab();

    fireEvent.click(screen.getByTestId("eval-cancel-button"));
    expect(
      screen.getByRole("button", { name: "确认终止?" }),
    ).toBeTruthy();
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "确认终止?" }));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("评测已终止", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
  });

  it("终止失败走错误 toast", () => {
    const mutate = rs.fn(
      (_input: unknown, opts?: { onError?: (e: Error) => void }) => {
        opts?.onError?.(new Error("boom"));
      },
    );
    hooksMock.useCancelEvalRun.mockReturnValue({ mutate, isPending: false });
    mockRunning();
    renderEvalTab();

    fireEvent.click(screen.getByTestId("eval-cancel-button"));
    fireEvent.click(screen.getByRole("button", { name: "确认终止?" }));
    expect(toast.error).toHaveBeenCalledWith("终止评测失败", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
  });

  it("确认态 3s 超时自动回退首态", () => {
    rs.useFakeTimers();
    mockRunning();
    renderEvalTab();

    fireEvent.click(screen.getByTestId("eval-cancel-button"));
    expect(
      screen.getByRole("button", { name: "确认终止?" }),
    ).toBeTruthy();
    act(() => {
      rs.advanceTimersByTime(2999);
    });
    expect(
      screen.getByRole("button", { name: "确认终止?" }),
    ).toBeTruthy();
    act(() => {
      rs.advanceTimersByTime(1);
    });
    expect(
      screen.queryByRole("button", { name: "确认终止?" }),
    ).toBeNull();
    expect(screen.getByTestId("eval-cancel-button")).toBeTruthy();
  });

  it("空闲态次槽还原 chevron 档位下拉", () => {
    hooksMock.useEvalRuns.mockReturnValue(
      queryState({ data: { in_flight: false, runs: [], total: 0 } }),
    );
    renderEvalTab();
    const toolbar = screen.getByTestId("eval-view-toolbar");
    expect(
      within(toolbar).getByRole("button", { name: "评测档位" }),
    ).toBeTruthy();
    expect(within(toolbar).queryByTestId("eval-cancel-button")).toBeNull();
  });

  it("窄档（⋯ 菜单）运行态含「终止评测」项，两步确认菜单不关", async () => {
    const original = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "eval-view-toolbar" ? 999 : 0;
      },
    });
    const mutate = rs.fn(
      (_input: unknown, opts?: { onSuccess?: () => void }) => {
        opts?.onSuccess?.();
      },
    );
    hooksMock.useCancelEvalRun.mockReturnValue({ mutate, isPending: false });
    mockRunning();
    try {
      renderEvalTab();
      // 降档是异步的（溢出检测走 effect）：先等 ⋯ 触发器就位，再 keyDown 开菜单
      //（Radix 在 jsdom 下 click 不开菜单，既有窄档用例同款手法）。
      await screen.findByTestId("eval-trend-chart-mock");
      const more = await waitFor(() =>
        within(screen.getByTestId("eval-view-toolbar")).getByRole("button", {
          name: "更多选项",
        }),
      );
      fireEvent.keyDown(more, { key: "ArrowDown" });
      const item = await screen.findByRole("menuitem", {
        name: "终止评测",
      });
      fireEvent.click(item);
      // 两步确认：菜单不关，项文案变「确认终止?」。
      expect(
        await screen.findByRole("menuitem", { name: "确认终止?" }),
      ).toBeTruthy();
      expect(mutate).not.toHaveBeenCalled();
      fireEvent.click(
        screen.getByRole("menuitem", { name: "确认终止?" }),
      );
      expect(mutate).toHaveBeenCalledTimes(1);
      expect(toast.success).toHaveBeenCalledWith("评测已终止", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "scrollWidth", original);
      } else {
        delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
      }
    }
  });
});
