/**
 * 触发链路集成测试（2026-09-06 验收缺口排查）：不 mock hooks、只 mock api 层，
 * 保留真实 TanStack useQuery，验证「点击触发 → onSuccess 乐观置位 setQueryData →
 * 按钮立即转运行态 + refetchInterval 启动(3s poll)」这条真实链路。
 *
 * 背景：eval-tab.dom.test 全量 mock 了 @/core/knowledge/hooks，因此只断言了
 * queryClient 缓存被改写，覆盖不到「缓存改写 → useQuery observer re-render →
 * 按钮/轮询响应」这一段；用户实测"触发后不切历史按钮不推进"正发生在这段。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const apiMock = rs.hoisted(() => ({
  getLatestEvalMetrics: rs.fn(),
  getEvalTrend: rs.fn(),
  listEvalRuns: rs.fn(),
  triggerEvalRun: rs.fn(),
}));
rs.mock("@/core/knowledge/api", () => apiMock);

// 重/无关子树占位：本测试只关心工具栏触发链路。
rs.mock("@/components/workspace/knowledge/eval-trend-chart", () => ({
  default: () => <div data-testid="eval-trend-chart-mock" />,
}));
rs.mock("@/components/workspace/knowledge/eval-question-bank", () => ({
  EvalQuestionBank: () => <div data-testid="eval-questions-view" />,
}));
rs.mock("@/components/workspace/knowledge/eval-run-history", () => ({
  EvalRunHistory: () => <div data-testid="eval-history-view" />,
}));
rs.mock("@/components/workspace/knowledge/eval-run-drawer", () => ({
  EvalRunDrawer: () => null,
}));

import { EvalTab } from "@/components/workspace/knowledge/eval-tab";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { EvalRunListResponse } from "@/core/knowledge/types";

const OVERVIEW = { kb_id: "kb-1", layer1: null, layer2: null };
const TREND = { points: [], baseline: null, has_data: false };

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <QueryClientProvider client={queryClient}>
        <EvalTab enabled kbId="kb-1" />
      </QueryClientProvider>
    </I18nContext.Provider>,
  );
  return { ...view, queryClient };
}

afterEach(() => {
  cleanup();
  apiMock.getLatestEvalMetrics.mockReset();
  apiMock.getEvalTrend.mockReset();
  apiMock.listEvalRuns.mockReset();
  apiMock.triggerEvalRun.mockReset();
});

describe("EvalTab 触发链路（真实 useQuery）", () => {
  it("快速档触发后按钮立即转运行态（不等 poll、不切视图）", async () => {
    apiMock.getLatestEvalMetrics.mockResolvedValue(OVERVIEW);
    apiMock.getEvalTrend.mockResolvedValue(TREND);
    apiMock.listEvalRuns.mockResolvedValue({
      in_flight: false,
      progress: null,
      runs: [],
      total: 0,
    });
    apiMock.triggerEvalRun.mockResolvedValue({ status: "enqueued" });

    renderTab();
    await waitFor(() => expect(apiMock.listEvalRuns).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "快速评测" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    // 乐观置位后按钮应立即离开 idle（无需等 3s poll / 无需切历史）。
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "快速评测" })).toBeNull();
    });
    // 快速档 layer1 → 无计数「检索评测」。
    expect(screen.getByRole("button", { name: "检索评测" })).toBeTruthy();
  });

  it("触发后 refetchInterval 启动：3s 内 listEvalRuns 被再次调用", async () => {
    apiMock.getLatestEvalMetrics.mockResolvedValue(OVERVIEW);
    apiMock.getEvalTrend.mockResolvedValue(TREND);
    apiMock.listEvalRuns.mockResolvedValue({
      in_flight: false,
      progress: null,
      runs: [],
      total: 0,
    });
    apiMock.triggerEvalRun.mockResolvedValue({ status: "enqueued" });

    renderTab();
    await waitFor(() => expect(apiMock.listEvalRuns).toHaveBeenCalled());
    const callsAfterMount = apiMock.listEvalRuns.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));

    // 乐观置位 in_flight=true 应使 refetchInterval=3000 生效 → 再次 fetch。
    await waitFor(
      () => {
        expect(apiMock.listEvalRuns.mock.calls.length).toBeGreaterThan(callsAfterMount);
      },
      { timeout: 6000 },
    );
  });

  it("在飞首查的旧结果不得覆盖乐观置位（竞态复现/修复验证）", async () => {
    apiMock.getLatestEvalMetrics.mockResolvedValue(OVERVIEW);
    apiMock.getEvalTrend.mockResolvedValue(TREND);
    // 首查挂在飞（延迟 resolve），模拟"触发前发出、触发后才回"的旧请求。
    let resolveFirst: ((value: EvalRunListResponse) => void) | undefined;
    const first = new Promise<EvalRunListResponse>((resolve) => {
      resolveFirst = resolve;
    });
    apiMock.listEvalRuns.mockImplementationOnce(() => first);
    apiMock.listEvalRuns.mockResolvedValue({
      in_flight: true,
      progress: null,
      runs: [],
      total: 0,
    });
    apiMock.triggerEvalRun.mockResolvedValue({ status: "enqueued" });

    renderTab();
    await waitFor(() => expect(apiMock.listEvalRuns).toHaveBeenCalled());
    // 首查在飞 → data undefined → 按钮 idle 可点。
    fireEvent.click(screen.getByRole("button", { name: "快速评测" }));
    // 乐观置位 → 按钮立即 running。
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "快速评测" })).toBeNull();
    });

    // 在飞首查此时才 resolve，携触发前的旧值 in_flight=false。
    act(() => {
      resolveFirst?.({ in_flight: false, progress: null, runs: [], total: 0 });
    });

    // 旧首查结果不得覆盖乐观值：按钮应保持 running（否则 poll 死、回 idle）。
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "快速评测" })).toBeNull();
    });
  });
});
