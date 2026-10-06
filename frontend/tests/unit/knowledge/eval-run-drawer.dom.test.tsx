/**
 * 单次评测运行详情 drawer 壳（2026-08-24 spec §5，plan Task 6；2026-09-08
 * 容器化 + 裸奔退役重设计）：
 * - 趋势图数据点点击下钻的数据源（useEvalRun mock 注入）；
 * - sticky 身份头（运行时间 mono 标题 + 环境/状态/评测内容/基线/回退芯片行）
 *   + 三张 bg-card 卡（运行信息：run_id 代码底 + 复制 / 完整时间；两层指标
 *   两列内凹瓦片 + 三色进度条）；Layer 2 的 path_accuracy 口径 callout 必须
 *   可见（与 Layer 1 同名指标口径不同，spec §5 冻结契约）；
 * - 层未执行（*_metrics 为 {}）渲染「未执行」提示；null 值瓦片 opacity-60 +
 *   破折号无进度条；
 * - 复制钮走 navigator.clipboard + toast（settings 集成页同款）；
 * - onOpenChange(false) 关闭（对齐 ChunkDrawer 的 Sheet 模式）。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

const hooksMock = rs.hoisted(() => ({
  useEvalRun: rs.fn(),
}));

rs.mock("@/core/knowledge/hooks", () => ({
  useEvalRun: hooksMock.useEvalRun,
}));

import { EvalRunDrawer } from "@/components/workspace/knowledge/eval-run-drawer";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { EvalRunDetail } from "@/core/knowledge/types";

const EVAL_RUN: EvalRunDetail = {
  run_id: "run-l1-1",
  kb_id: "kb-1",
  status: "completed",
  environment: "local",
  created_at: "2026-08-20T09:00:00+00:00",
  layer1_metrics: {
    summary: { hit_rate: 0.928, recall_at_k: 0.897, mrr: 0.812, path_accuracy: 0.946, question_count: 20 },
    fact: { hit_rate: 0.952, recall_at_k: 0.923, mrr: 0.876, path_accuracy: 0.985, question_count: 12 },
  },
  layer2_metrics: {
    ragas_available: true,
    ragas: { faithfulness: 0.933, answer_relevancy: 0.877, context_precision: 0.912, context_recall: 0.864 },
    arch_specific: { citation_precision: 0.91, citation_recall: 0.85, seed_hit_rate: 0.75 },
    langfuse_trace_url: "https://langfuse.example/trace/1",
    has_graph_questions: true,
    path_accuracy: 0.87,
  },
  baseline_diff: { recall_at_k_delta: -0.01, regression_detected: false, threshold_percent: 3 },
  is_baseline: true,
};

function renderDrawer(props?: { runId?: string | null; onOpenChange?: (open: boolean) => void }) {
  const onOpenChange = props?.onOpenChange ?? rs.fn();
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <EvalRunDrawer
        kbId="kb-1"
        open
        runId={props?.runId === undefined ? "run-l1-1" : props.runId}
        onOpenChange={onOpenChange}
      />
    </I18nContext.Provider>,
  );
  return { onOpenChange };
}

describe("EvalRunDrawer", () => {
  beforeEach(() => {
    hooksMock.useEvalRun.mockReset();
    hooksMock.useEvalRun.mockReturnValue({ data: EVAL_RUN, isLoading: false, error: null });
  });

  afterEach(() => {
    cleanup();
  });

  it("fetches via useEvalRun with kbId+runId and renders containerized run metadata", () => {
    renderDrawer();
    expect(hooksMock.useEvalRun).toHaveBeenCalledWith("kb-1", "run-l1-1");
    // 运行信息卡：run_id 代码底 + 卡头词汇；环境本地化胶囊；状态芯片；基线琥珀胶囊；评测内容芯片
    expect(screen.getByText("run-l1-1")).toBeTruthy();
    expect(screen.getByText("运行 ID")).toBeTruthy();
    expect(screen.getByText("运行信息")).toBeTruthy();
    expect(screen.getByText("本地")).toBeTruthy();
    expect(screen.getByText("已完成")).toBeTruthy();
    expect(screen.getByText("基线")).toBeTruthy();
    expect(screen.getByText("完整")).toBeTruthy();
    // 三张 bg-card 容器（运行信息 / 检索质量 / 生成质量）——裸奔退役
    expect(document.querySelectorAll("section.bg-card").length).toBe(3);
    // 内部代号禁现守卫（历史表同纪律）
    expect(screen.queryByText(/L1|L2/)).toBeNull();
  });

  it("sticky identity header carries mono run time title and full time in info card", () => {
    renderDrawer();
    // 身份标题 = 运行时间 mono（MM-DD HH:mm 词汇同历史表）
    expect(screen.getByTestId("eval-drawer-title").textContent).toMatch(
      /\d{2}-\d{2} \d{2}:\d{2}/,
    );
    // 完整时间直显（toLocaleString 退役）：含年月日（zh 格式为斜杠分隔）
    expect(screen.getByTestId("eval-drawer-created-at").textContent).toMatch(
      /\d{4}[/-]\d{2}[/-]\d{2}/,
    );
  });

  it("renders both layer summaries as tiles including the Layer 2 path_accuracy caveat", () => {
    renderDrawer();
    // 检索质量：summary 四瓦片 + 题量计数徽章（区块标题已去 Layer 术语）
    expect(screen.getByText("检索质量")).toBeTruthy();
    expect(screen.getByText("n=20")).toBeTruthy();
    const hitTile = screen.getByTestId("eval-drawer-tile-hit_rate");
    expect(
      within(hitTile).getByTestId("eval-drawer-tile-value-hit_rate").textContent,
    ).toBe("92.8%");
    // 瓦片带三色进度条（总览 MetricTile 同词汇）
    expect(hitTile.querySelector('[data-slot="progress-indicator"]')).toBeTruthy();
    expect(
      screen.getByTestId("eval-drawer-tile-value-recall_at_k").textContent,
    ).toBe("89.7%");
    expect(screen.getByTestId("eval-drawer-tile-value-mrr").textContent).toBe(
      "81.2%",
    );
    // 生成质量：RAGAS 四项 + 架构专属三项 + path_accuracy 及口径 callout
    // （RAGAS 行名与总览卡/趋势图例同词汇，2026-09-05 闭环后为中文）。
    expect(screen.getByText("生成质量")).toBeTruthy();
    expect(screen.getByText("忠实度")).toBeTruthy();
    expect(screen.getByText("上下文召回率")).toBeTruthy();
    expect(screen.getByText("引用准确率")).toBeTruthy();
    expect(screen.getByText("路由命中率")).toBeTruthy();
    expect(
      screen.getByTestId("eval-drawer-tile-value-routing_hit_rate").textContent,
    ).toBe("87.0%");
    expect(
      screen.getByText(/与检索质量的路径准确率（离线检索选路）口径不同/),
    ).toBeTruthy();
  });

  it("regression run shows the red regression chip in the identity header", () => {
    hooksMock.useEvalRun.mockReturnValue({
      data: {
        ...EVAL_RUN,
        baseline_diff: {
          recall_at_k_delta: -0.12,
          regression_detected: true,
          threshold_percent: 3,
        },
      },
      isLoading: false,
      error: null,
    });
    renderDrawer();
    expect(screen.getByText("检测到回退")).toBeTruthy();
  });

  it("null metric tile renders dash with opacity and no progress bar", () => {
    hooksMock.useEvalRun.mockReturnValue({
      data: {
        ...EVAL_RUN,
        layer2_metrics: {
          ragas_available: true,
          ragas: { faithfulness: 0.933, answer_relevancy: 0.877, context_precision: 0.912, context_recall: 0.864 },
          arch_specific: { citation_precision: 0.91, citation_recall: 0.85, seed_hit_rate: 0.75 },
          has_graph_questions: true,
          path_accuracy: null,
        },
      },
      isLoading: false,
      error: null,
    });
    renderDrawer();
    const tile = screen.getByTestId("eval-drawer-tile-routing_hit_rate");
    expect(tile.className).toContain("opacity-60");
    expect(
      screen.getByTestId("eval-drawer-tile-value-routing_hit_rate").textContent,
    ).toBe("-");
    expect(tile.querySelector('[data-slot="progress-indicator"]')).toBeNull();
  });

  it("copies run id via the clipboard button", () => {
    const writeText = rs.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    renderDrawer();
    fireEvent.click(screen.getByTestId("eval-drawer-copy-run-id"));
    // writeText 在 onClick 同步段即被调用（await 只等结果）
    expect(writeText).toHaveBeenCalledWith("run-l1-1");
  });

  it("renders not-executed hints for layers whose metrics are empty objects", () => {
    hooksMock.useEvalRun.mockReturnValue({
      data: {
        ...EVAL_RUN,
        layer1_metrics: {},
        layer2_metrics: {},
      },
      isLoading: false,
      error: null,
    });
    renderDrawer();
    const hints = screen.getAllByText("本次运行未执行该层");
    expect(hints.length).toBe(2);
    expect(screen.queryByText("路由命中率")).toBeNull();
  });

  it("shows loading then error copy from the query state", () => {
    hooksMock.useEvalRun.mockReturnValue({ data: undefined, isLoading: true, error: null });
    renderDrawer();
    expect(screen.getByText("加载中…")).toBeTruthy();

    cleanup();
    hooksMock.useEvalRun.mockReturnValue({ data: undefined, isLoading: false, error: new Error("boom") });
    renderDrawer();
    expect(screen.getByText("评测数据加载失败")).toBeTruthy();
  });

  it("cancelled 行状态徽标显「已终止」（spec §11，不再落入 skipped 兑底）", () => {
    hooksMock.useEvalRun.mockReturnValue({
      data: { ...EVAL_RUN, status: "cancelled" },
      isLoading: false,
      error: null,
    });
    renderDrawer();
    expect(screen.getByText("已终止")).toBeTruthy();
    expect(screen.queryByText("已跳过")).toBeNull();
  });

  it("closes via onOpenChange(false)", () => {
    const { onOpenChange } = renderDrawer();
    // shadcn SheetContent 自带关闭按钮（sr-only 文本 Close）
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("renders nothing when runId is null (drawer closed)", () => {
    renderDrawer({ runId: null });
    expect(screen.queryByText("评测运行详情")).toBeNull();
  });
});
