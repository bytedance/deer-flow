/**
 * 运行进度容器（spec 2026-09-06 §9 Task 11）：
 * - 第一行 = 单轨时长加权整体条（段边界刻线 + 当前段跨度提亮 + 连续填充）+ 右侧仅 ETA；
 * - 第二行 = 单行实时日志（结构化 tail → i18n 句，aria-live=polite）+ failed 徽标；
 * - ETA warmup 不足时显示「估算中…」而不是假数字；快速档只有一段（无刻线）。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { EvalRunBanner } from "@/components/workspace/knowledge/eval-run-banner";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { etaSeconds, overallFraction } from "@/core/knowledge/eval-run-status";
import type { EvalRunProgress, EvalRunSummary } from "@/core/knowledge/types";

const iso = (msOffset: number) => new Date(Date.now() + msOffset).toISOString();

function progress(overrides: Partial<EvalRunProgress> = {}): EvalRunProgress {
  return {
    run_id: "run-1",
    phase: "questions",
    done: 3,
    total: 10,
    failed: 0,
    started_at: iso(-5_000),
    updated_at: iso(0),
    phase_started_at: iso(-5_000),
    phase_durations: {},
    tail: { kind: "item", phase: "questions", done: 3, total: 10, failed: 0 },
    ...overrides,
  };
}

function renderBanner(props: {
  progress?: EvalRunProgress | null;
  tier?: "l1" | "l1_l2";
  running?: boolean;
  lastRun?: EvalRunSummary | null;
  onViewHistory?: () => void;
}) {
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <EvalRunBanner
        progress={props.progress ?? null}
        tier={props.tier ?? "l1_l2"}
        running={props.running ?? true}
        lastRun={props.lastRun ?? null}
        onViewHistory={props.onViewHistory ?? (() => undefined)}
      />
    </I18nContext.Provider>,
  );
}

function summaryRun(overrides: Partial<EvalRunSummary> = {}): EvalRunSummary {
  return {
    run_id: "run-last",
    created_at: iso(-312_000),
    completed_at: iso(-60_000),
    environment: "local",
    status: "completed",
    is_baseline: false,
    has_layer1: true,
    has_layer2: false,
    regression_detected: false,
    langfuse_trace_url: null,
    ...overrides,
  };
}

const percent = (value: number) => `${Math.round(value * 100)}%`;

afterEach(cleanup);

describe("EvalRunBanner 加权条", () => {
  it("fills to the weighted overall fraction and exposes progressbar semantics", () => {
    const snapshot = progress({ phase: "questions", done: 3, total: 10 });
    renderBanner({ progress: snapshot });

    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.getAttribute("aria-valuenow")).toBe(String(Math.round(overallFraction(snapshot, "l1_l2") * 100)));
    expect(bar.getAttribute("aria-label")).toContain("答题评测");

    expect(screen.getByTestId("eval-banner-fill").style.width).toBe(percent(overallFraction(snapshot, "l1_l2")));
  });

  it("draws one tick per phase boundary and highlights the current span", () => {
    renderBanner({ progress: progress({ phase: "questions" }) });

    // 冷启动先验 10/35/55 → 刻线在 10% 与 45%，当前段（答题）跨度 10%→45%。
    const ticks = screen.getAllByTestId("eval-banner-tick");
    expect(ticks.map((tick) => tick.style.left)).toEqual(["10%", "45%"]);

    const span = screen.getByTestId("eval-banner-span");
    expect(span.style.left).toBe("10%");
    expect(span.style.width).toBe("35%");
  });

  it("collapses the quick tier to a single span without ticks", () => {
    renderBanner({ progress: progress({ phase: "layer1", done: 0, total: 1 }), tier: "l1" });

    expect(screen.queryAllByTestId("eval-banner-tick")).toHaveLength(0);
    expect(screen.getByTestId("eval-banner-span").style.width).toBe("100%");
    expect(screen.getByTestId("eval-banner-fill").style.width).toBe("0%");
  });

  it("renders an empty bar during the optimistic window (no progress yet)", () => {
    renderBanner({ progress: null });

    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("0");
    expect(screen.getByTestId("eval-banner-fill").style.width).toBe("0%");
  });
});

describe("EvalRunBanner ETA", () => {
  it("withholds the estimate during warmup", () => {
    // 本段已跑 3s < 5s 门控 → 不给数字。
    renderBanner({ progress: progress({ started_at: iso(-3_000), phase_started_at: iso(-3_000) }) });

    expect(screen.getByTestId("eval-banner-eta").textContent).toBe("估算中…");
  });

  it("extrapolates the remaining minutes once warmed up", () => {
    // layer1 实测 20s（先验占比 0.1 → 本段速率定价）：questions 半程用 40s →
    // 本段全程 80s、剩 40s；质量段 0.55/0.35 × 80s ≈ 125.7s → ETA ≈ 165.7s ≈ 3 分钟。
    renderBanner({
      progress: progress({
        phase: "questions",
        done: 5,
        total: 10,
        started_at: iso(-60_000),
        phase_started_at: iso(-40_000),
        phase_durations: { layer1: 20 },
      }),
    });

    expect(screen.getByTestId("eval-banner-eta").textContent).toBe("预计剩余 ~3 分钟");
  });

  it("shows seconds for sub-minute estimates (quick tier)", () => {
    // elapsed 7s（远离 2.5s 取整边界 → remaining≈2.92，组件渲染与断言两次采样
    // 不会跨档 flaky）。
    const snapshot = progress({
      phase: "layer1",
      done: 12,
      total: 17,
      started_at: iso(-7_000),
      phase_started_at: iso(-7_000),
      tail: { kind: "item", phase: "layer1", done: 12, total: 17, failed: 0 },
    });
    renderBanner({ progress: snapshot, tier: "l1" });

    // 快速档全程只有几秒：分钟粒度会说"~1 分钟"而撒谎，故用秒。
    const eta = etaSeconds(snapshot, "l1");
    expect(eta).not.toBeNull();
    expect(screen.getByTestId("eval-banner-eta").textContent).toBe(
      `预计剩余 ~${Math.max(1, Math.round(eta ?? 0))}s`,
    );
  });
});

describe("EvalRunBanner 单行日志", () => {
  it("renders the tail event through i18n on a polite live region", () => {
    renderBanner({ progress: progress({ tail: { kind: "item", phase: "questions", done: 3, total: 10, failed: 0 } }) });

    const log = screen.getByTestId("eval-banner-log");
    expect(log.getAttribute("aria-live")).toBe("polite");
    expect(log.textContent).toContain("答题评测 3/10");
  });

  it("announces phase transitions and failure events", () => {
    const { rerender } = render(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <EvalRunBanner progress={progress({ tail: { kind: "phase", phase: "ragas", done: 0, total: 20, failed: 0 } })} tier="l1_l2" />
      </I18nContext.Provider>,
    );
    expect(screen.getByTestId("eval-banner-log").textContent).toContain("进入质量评估");

    rerender(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <EvalRunBanner progress={progress({ failed: 2, tail: { kind: "fail", phase: "questions", done: 4, total: 10, failed: 2 } })} tier="l1_l2" />
      </I18nContext.Provider>,
    );
    const log = screen.getByTestId("eval-banner-log");
    expect(log.textContent).toContain("答题评测 4/10");
    expect(log.textContent).toContain("失败 2");
  });

  it("falls back to a waiting line when the registry has no tail yet", () => {
    renderBanner({ progress: progress({ tail: null }) });

    expect(screen.getByTestId("eval-banner-log").textContent).toContain("等待首个进度事件");
  });

  it("keeps the failed badge out of the way when nothing failed", () => {
    renderBanner({ progress: progress({ failed: 0, tail: { kind: "item", phase: "questions", done: 3, total: 10, failed: 0 } }) });

    expect(within(screen.getByTestId("eval-banner-log")).queryByTestId("eval-banner-failed")).toBeNull();
  });
});

// ── 空闲态状态槽（spec 2026-09-06 §10）─────────────────────

describe("EvalRunBanner 空闲态槽", () => {
  it("shows the last-run one-line summary when idle", () => {
    renderBanner({ running: false, lastRun: summaryRun() });

    const slot = screen.getByTestId("eval-run-banner");
    // 252s → 4m 12s（单位 s/m，2026-09-06 用户定案）；has_layer2=false → 快速档；
    // 无前缀「上次评测」；档位带图标；字号升档 text-sm；相对时间跟 UI locale（zh）。
    expect(slot.textContent).toContain("快速评测 · 耗时 4m 12s");
    expect(slot.textContent).not.toContain("上次评测");
    expect(within(slot).getByTestId("eval-slot-tier-icon")).toBeTruthy();
    expect(within(slot).getByTestId("eval-slot-text").className).toContain("text-sm");
    expect(slot.textContent).toContain("5 分钟前");
    // 空闲态不残留进度条语义。
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("omits the duration segment when stamps are missing", () => {
    renderBanner({ running: false, lastRun: summaryRun({ completed_at: null }) });

    const text = screen.getByTestId("eval-run-banner").textContent;
    expect(text).toContain("快速评测");
    expect(text).not.toContain("耗时");
    expect(text).not.toContain("上次评测");
  });

  it("tints failed runs destructive and drops the duration", () => {
    renderBanner({ running: false, lastRun: summaryRun({ status: "error" }) });

    const slot = screen.getByTestId("eval-run-banner");
    expect(slot.textContent).toContain("评测失败");
    expect(slot.textContent).not.toContain("上次评测");
    expect(slot.textContent).not.toContain("耗时");
    expect(within(slot).getByTestId("eval-slot-text").className).toContain("text-destructive");
  });

  it("cancelled 行专属文案「评测已终止」（区别 failed，spec §11）", () => {
    renderBanner({ running: false, lastRun: summaryRun({ status: "cancelled" }) });

    const slot = screen.getByTestId("eval-run-banner");
    expect(slot.textContent).toContain("评测已终止");
    expect(slot.textContent).not.toContain("评测失败");
    expect(slot.textContent).not.toContain("耗时");
    // 色调同非 completed（destructive），文案区分终止与失败。
    expect(within(slot).getByTestId("eval-slot-text").className).toContain("text-destructive");
  });

  it("jumps to the history view via the slot button", () => {
    const onViewHistory = rs.fn(() => undefined);
    renderBanner({ running: false, lastRun: summaryRun(), onViewHistory });

    fireEvent.click(screen.getByTestId("eval-slot-history"));
    expect(onViewHistory.mock.calls.length).toBe(1);
  });

  it("renders the muted never-ran line without history", () => {
    renderBanner({ running: false, lastRun: null });

    const slot = screen.getByTestId("eval-run-banner");
    expect(slot.textContent).toContain("尚未评测");
    expect(screen.queryByTestId("eval-slot-history")).toBeNull();
  });
});
