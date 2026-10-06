/**
 * eval-run-status pure-function tests (spec 2026-09-06 run-progress §4/§5 + §9).
 *
 * 覆盖运行进度纯函数：phaseStep 把三段映射到 1/2/3（null/undefined 降级为 1，让
 * 触发瞬间即读「检索评测 1/3」）；§9 加权进度条三件套 adaptiveWeights /
 * overallFraction / etaSeconds + etaMinutes（先验与实测自适应、warmup 门控、分钟取整）；
 * 以及 runningTier（在飞那次运行的档位推断）。底缘细线退役后
 * progressFraction / isIndeterminatePhase / progressAriaLabel 一并删除（无生产消费者）。
 * §10 状态槽摘要派生三件：durationParts / tierOfRun / runDurationSeconds
 * （相对时间复用 @/core/utils/datetime 的 formatTimeAgo，不另造纯函数）。
 */
import { describe, expect, it } from "@rstest/core";

import {
  EVAL_PHASE_ORDER,
  adaptiveWeights,
  durationParts,
  etaMinutes,
  etaSeconds,
  overallFraction,
  phaseStep,
  runDurationSeconds,
  runningTier,
  tierOfRun,
} from "@/core/knowledge/eval-run-status";
import type { EvalRunProgress, EvalRunSummary } from "@/core/knowledge/types";

function progress(overrides: Partial<EvalRunProgress> = {}): EvalRunProgress {
  return {
    run_id: "run-1",
    phase: "questions",
    done: 3,
    total: 10,
    failed: 0,
    started_at: "2026-09-06T10:00:00+00:00",
    updated_at: "2026-09-06T10:05:00+00:00",
    ...overrides,
  };
}

describe("phaseStep", () => {
  it("maps each phase to its 1-based step in the 3-phase pipeline", () => {
    expect(phaseStep(progress({ phase: "layer1" }))).toBe(1);
    expect(phaseStep(progress({ phase: "questions" }))).toBe(2);
    expect(phaseStep(progress({ phase: "ragas" }))).toBe(3);
  });

  it("defaults to step 1 (layer1) when there is no live progress", () => {
    // 触发瞬间乐观置位但首个轮询未到 → 按钮即读「检索评测 1/3」。
    expect(phaseStep(null)).toBe(1);
    expect(phaseStep(undefined)).toBe(1);
  });
});

// ── 加权整体进度条（spec 2026-09-06 §9 Task 10）─────────────────────

const T0 = Date.parse("2026-09-06T10:00:00+00:00");
const iso = (ms: number) => new Date(ms).toISOString();

describe("adaptiveWeights", () => {
  it("falls back to the prior split when nothing has been measured yet", () => {
    const weights = adaptiveWeights(progress({ phase: "layer1", done: 0, total: 1 }), "l1_l2", T0 + 1000);

    expect(weights.layer1).toBeCloseTo(0.1);
    expect(weights.questions).toBeCloseTo(0.35);
    expect(weights.ragas).toBeCloseTo(0.55);
    expect((weights.layer1 ?? 0) + (weights.questions ?? 0) + (weights.ragas ?? 0)).toBeCloseTo(1);
    expect(EVAL_PHASE_ORDER).toEqual(["layer1", "questions", "ragas"]);
  });

  it("collapses the quick tier to its single phase", () => {
    expect(adaptiveWeights(progress({ phase: "layer1" }), "l1", T0)).toEqual({ layer1: 1 });
  });

  it("replaces measured phases and rescales the remaining spans by the prior ratio", () => {
    // layer1 30s + questions 20s 实测，先验占比 0.45 → scale 111.1s，ragas 期望 61.1s。
    const weights = adaptiveWeights(progress({ phase: "ragas", done: 0, total: 4, phase_started_at: iso(T0 + 50_000), phase_durations: { layer1: 30, questions: 20 } }), "l1_l2", T0 + 60_000);

    expect(weights.layer1).toBeCloseTo(0.27, 2);
    expect(weights.questions).toBeCloseTo(0.18, 2);
    expect(weights.ragas).toBeCloseTo(0.55, 2);
  });

  it("clamps a zero measured duration so the span cannot collapse", () => {
    // layer1 亚秒完成（实测 0s）不得让权重归零或污染总量。
    const weights = adaptiveWeights(progress({ phase: "questions", done: 0, total: 4, phase_started_at: iso(T0), phase_durations: { layer1: 0 } }), "l1_l2", T0 + 500);

    expect(weights.layer1).toBeGreaterThan(0);
    expect(Number.isFinite(weights.questions)).toBe(true);
    expect(Number.isFinite(weights.ragas)).toBe(true);
  });

  it("grows the current span once the phase overruns its expectation", () => {
    // scale = 30/0.1 = 300 → questions 期望 105s，但已跑 270s → 取大者。
    const weights = adaptiveWeights(progress({ phase: "questions", done: 1, total: 4, phase_started_at: iso(T0 + 30_000), phase_durations: { layer1: 30 } }), "l1_l2", T0 + 300_000);

    expect(weights.questions).toBeCloseTo(270 / 465, 2);
    expect(weights.ragas).toBeCloseTo(165 / 465, 2);
  });

  it("ignores the current phase's elapsed time until the scale is calibrated", () => {
    // 冷启动（零实测）时先验是无量纲占比，不能与已跑秒数比大小——
    // 否则条一开跑就被拉宽，先验几何全失。
    const weights = adaptiveWeights(progress({ phase: "questions", done: 0, total: 4, phase_started_at: iso(T0), phase_durations: {} }), "l1_l2", T0 + 60_000);

    expect(weights.layer1).toBeCloseTo(0.1);
    expect(weights.questions).toBeCloseTo(0.35);
    expect(weights.ragas).toBeCloseTo(0.55);
  });
});

describe("overallFraction", () => {
  it("adds the completed spans plus the current span's within-phase share", () => {
    expect(overallFraction(progress({ phase: "layer1", done: 0, total: 1 }), "l1_l2", T0 + 1000)).toBeCloseTo(0);
    expect(overallFraction(progress({ phase: "questions", done: 3, total: 10 }), "l1_l2", T0 + 1000)).toBeCloseTo(0.205);
    expect(overallFraction(progress({ phase: "ragas", done: 2, total: 4 }), "l1_l2", T0 + 1000)).toBeCloseTo(0.725);
  });

  it("is monotonic across phases and reaches 1 at the end", () => {
    const early = overallFraction(progress({ phase: "questions", done: 3, total: 10 }), "l1_l2", T0 + 1000);
    const later = overallFraction(progress({ phase: "questions", done: 7, total: 10 }), "l1_l2", T0 + 1000);
    const scoring = overallFraction(progress({ phase: "ragas", done: 0, total: 4 }), "l1_l2", T0 + 1000);
    const end = overallFraction(progress({ phase: "ragas", done: 4, total: 4 }), "l1_l2", T0 + 1000);

    expect(early).toBeLessThan(later);
    expect(later).toBeLessThan(scoring);
    expect(end).toBeCloseTo(1);
  });

  it("guards a non-positive total and a missing progress", () => {
    const stalled = overallFraction(progress({ phase: "ragas", done: 0, total: 0 }), "l1_l2", T0 + 1000);

    expect(Number.isNaN(stalled)).toBe(false);
    expect(stalled).toBeCloseTo(0.45);
    expect(overallFraction(null, "l1_l2", T0)).toBe(0);
    expect(overallFraction(undefined, "l1_l2", T0)).toBe(0);
  });

  it("clamps an over-count done to the span end", () => {
    expect(overallFraction(progress({ phase: "questions", done: 99, total: 10 }), "l1_l2", T0 + 1000)).toBeCloseTo(0.45);
  });
});

describe("etaSeconds", () => {
  it("withholds the estimate until the current phase has a rate", () => {
    // 本段零完成（无速率）或本段已跑不足 5s → 不给数字，也不拿廉价段速率冒充全程。
    expect(etaSeconds(progress({ phase: "layer1", done: 0, total: 1 }), "l1_l2", T0 + 600_000)).toBeNull();
    expect(etaSeconds(progress({ phase: "questions", done: 3, total: 10, phase_started_at: iso(T0 + 57_000) }), "l1_l2", T0 + 60_000)).toBeNull();
    expect(etaSeconds(null, "l1_l2", T0 + 60_000)).toBeNull();
  });

  it("extrapolates the current phase rate and prices future phases by the prior ratio", () => {
    // questions 半程用 60s → 本段全程 120s、剩 60s；质量段按先验占比定价
    // 0.55/0.35 × 120s ≈ 188.6s → ETA ≈ 248.6s（而非 f 外推的 ~158s 乐观值）。
    const eta = etaSeconds(progress({ phase: "questions", done: 5, total: 10, phase_started_at: iso(T0) }), "l1_l2", T0 + 60_000);

    expect(eta).toBeCloseTo(60 + (0.55 / 0.35) * 120, 0);
  });

  it("has no future phases to price in the quick tier", () => {
    // layer1 12/17 用 6s → 全程 8.5s、剩 2.5s。
    const eta = etaSeconds(progress({ phase: "layer1", done: 12, total: 17, phase_started_at: iso(T0) }), "l1", T0 + 6_000);

    expect(eta).toBeCloseTo(2.5, 1);
  });

  it("never goes negative at the end of the run", () => {
    expect(etaSeconds(progress({ phase: "ragas", done: 4, total: 4, phase_started_at: iso(T0) }), "l1_l2", T0 + 60_000)).toBe(0);
  });
});

describe("etaMinutes", () => {
  it("rounds to whole minutes with a 1-minute floor and passes null through", () => {
    expect(etaMinutes(null)).toBeNull();
    expect(etaMinutes(90)).toBe(2);
    expect(etaMinutes(10)).toBe(1);
    expect(etaMinutes(0)).toBe(1);
  });
});

describe("runningTier", () => {
  it("infers the full tier once the run has left layer1", () => {
    // 页面刷新后接上在飞的 run：phase 已离开 layer1 就必属完整档。
    expect(runningTier(progress({ phase: "questions" }), null, "l1")).toBe("l1_l2");
    expect(runningTier(progress({ phase: "ragas" }), null, "l1")).toBe("l1_l2");
  });

  it("uses the tier recorded at trigger time while still in layer1", () => {
    // 从题库右键触发的完整档不得被当前单选（快速档）覆盖。
    expect(runningTier(progress({ phase: "layer1" }), "l1_l2", "l1")).toBe("l1_l2");
  });

  it("falls back to the selected tier when nothing is known yet", () => {
    expect(runningTier(null, null, "l1_l2")).toBe("l1_l2");
    expect(runningTier(progress({ phase: "layer1" }), null, "l1")).toBe("l1");
  });
});

// ── 状态槽摘要派生（spec 2026-09-06 §10）─────────────────────

function run(overrides: Partial<EvalRunSummary> = {}): EvalRunSummary {
  return {
    run_id: "run-slot",
    created_at: iso(-60_000),
    completed_at: iso(-30_000),
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

describe("tierOfRun", () => {
  it("reads the tier from the persisted layer presence", () => {
    // 零迁移派生：has_layer2 即完整档（历史行序列化已具备该旗标）。
    expect(tierOfRun(run())).toBe("l1");
    expect(tierOfRun(run({ has_layer2: true }))).toBe("l1_l2");
  });
});

describe("runDurationSeconds", () => {
  it("subtracts created_at from completed_at", () => {
    expect(runDurationSeconds(run({ created_at: iso(-60_000), completed_at: iso(-30_000) }))).toBeCloseTo(30, 1);
  });

  it("withholds the duration when a stamp is missing or inverted", () => {
    // 缺戳/倒序（脏数据）→ null，摘要行省掉耗时段而不是显个假数字。
    expect(runDurationSeconds(run({ completed_at: null }))).toBeNull();
    expect(runDurationSeconds(run({ created_at: null }))).toBeNull();
    expect(runDurationSeconds(run({ created_at: iso(-10_000), completed_at: iso(-30_000) }))).toBeNull();
  });
});

describe("durationParts", () => {
  it("keeps sub-minute runs in seconds", () => {
    expect(durationParts(38)).toEqual({ kind: "seconds", value: 38 });
    expect(durationParts(59.4)).toEqual({ kind: "seconds", value: 59 });
  });

  it("splits minute runs into minutes and seconds", () => {
    expect(durationParts(252)).toEqual({ kind: "minutes-seconds", minutes: 4, seconds: 12 });
  });

  it("drops the zero remainder", () => {
    expect(durationParts(120)).toEqual({ kind: "minutes", value: 2 });
  });
});
