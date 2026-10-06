/**
 * Pure derivations over the eval runs payload (spec 2026-08-27 §5.3). The
 * polling cadence lives here — like wiki-status.ts — so the hook wiring stays
 * trivially testable.
 */
import type { EvalRunListResponse, EvalRunProgress, EvalRunSummary } from "./types";

/**
 * Polling cadence for the eval runs history while an on-demand run is in
 * flight — same 3s cadence as the documents and wiki queries; idle history
 * never polls.
 */
export const EVAL_RUNS_POLL_INTERVAL_MS = 3000;

/**
 * TanStack Query ``refetchInterval`` decision for the eval runs history:
 * poll only while the top-level ``in_flight`` flag reports a run in flight.
 * An undefined payload means the query is disabled or not yet fetched.
 */
export function evalRunsRefetchInterval(data: EvalRunListResponse | undefined): number | false {
  if (!data) return false;
  return data.in_flight ? EVAL_RUNS_POLL_INTERVAL_MS : false;
}

/**
 * True while the eval toolbar should render 运行中… — the pending flag covers
 * the click→first-poll gap (the 202 ack returns before the next poll sees the
 * top-level flag flip, wiki `isWikiUpdating` same-shape precedent).
 */
export function isEvalRunning(data: EvalRunListResponse | undefined, mutationPending: boolean): boolean {
  return mutationPending || (data?.in_flight ?? false);
}

/**
 * Total phases in the full-run pipeline (layer1 → questions → ragas). The
 * toolbar button renders the live phase as「阶段名 n/EVAL_PHASE_COUNT」so the
 * user always knows where in the pipeline the run is — the spec 2026-09-06
 * revision replaces the two indeterminate phases that both used to read a
 * bare, indistinguishable 运行中….
 */
export const EVAL_PHASE_COUNT = 3;

/**
 * 1-based position of the phase in the 3-phase pipeline. A running-without-
 * progress state (null / undefined — the optimistic window before the first
 * poll lands) defaults to step 1 so the button reads「检索评测 1/3」the instant
 * a full run is triggered.
 */
export function phaseStep(progress: EvalRunProgress | null | undefined): number {
  if (progress?.phase === "questions") return 2;
  if (progress?.phase === "ragas") return 3;
  return 1;
}

// ── 加权整体进度条（spec 2026-09-06 §9）─────────────────────────

/** 档位（run 的 layers）——决定流水线有几段：快速档只有 layer1。 */
export type EvalTier = "l1" | "l1_l2";

type EvalPhase = EvalRunProgress["phase"];

/** 各段占条的跨度权重（占比，总和 1）。 */
export type EvalPhaseWeights = Partial<Record<EvalPhase, number>>;

/** 流水线顺序：进度条的跨度与刻线按此排列。 */
export const EVAL_PHASE_ORDER: EvalPhase[] = ["layer1", "questions", "ragas"];

/**
 * 先验时长占比（冷启动猜测）：layer1 秒级、答题每题一次 agent run、质量评估
 * （ragas jobs + citation judge）是已知瓶颈。先验仅用于未实测前；某段一完成就用
 * 实测时长取代，因此无需任何历史存储字段。
 */
export const PHASE_WEIGHT_PRIOR: Record<EvalTier, EvalPhaseWeights> = {
  l1_l2: { layer1: 0.1, questions: 0.35, ragas: 0.55 },
  l1: { layer1: 1 },
};

/** 亚秒完成的段实测为 0s；下限避免它的跨度塌陷并污染 scale。 */
export const MIN_PHASE_SECONDS = 1;

/** 速率外推的 warmup 门控：本段至少跑满该秒数且已有完成量，速率才有意义。 */
export const ETA_WARMUP_SECONDS = 5;

function phasesFor(tier: EvalTier): EvalPhase[] {
  return tier === "l1" ? ["layer1"] : EVAL_PHASE_ORDER;
}

function parseMs(timestamp: string | null | undefined): number | null {
  if (!timestamp) return null;
  const ms = Date.parse(timestamp);
  return Number.isFinite(ms) ? ms : null;
}

/** 当前段；进度缺失或 phase 不属本档位时降级到首段（乐观窗口同款）。 */
function currentPhase(progress: EvalRunProgress | null | undefined, phases: EvalPhase[]): EvalPhase {
  const fallback = phases[0] ?? "layer1";
  return progress && phases.includes(progress.phase) ? progress.phase : fallback;
}

/**
 * 各段跨度的时长权重（spec 2026-09-06 §9）。
 *
 * 已完成段用实测时长；剩余段按先验比例缩放到已观测的速率（scale = 实测和 /
 * 已完成段先验和），因此条的几何会随运行自我校准而无需存储历史。当前段一旦
 * 超时，它的跨度会变宽（取期望与已跑时长的较大者）——慢的 ragas 段是把条拉长，
 * 而不是让条停在原地假装不动。
 */
export function adaptiveWeights(progress: EvalRunProgress | null | undefined, tier: EvalTier, nowMs: number = Date.now()): EvalPhaseWeights {
  const phases = phasesFor(tier);
  const prior = PHASE_WEIGHT_PRIOR[tier];
  const current = currentPhase(progress, phases);
  const measured = progress?.phase_durations ?? {};
  const currentIndex = phases.indexOf(current);

  let measuredSum = 0;
  let priorCompletedSum = 0;
  for (const phase of phases.slice(0, currentIndex)) {
    const observed = measured[phase];
    if (typeof observed === "number" && Number.isFinite(observed)) {
      measuredSum += Math.max(observed, MIN_PHASE_SECONDS);
      priorCompletedSum += prior[phase] ?? 0;
    }
  }
  const scale = priorCompletedSum > 0 && measuredSum > 0 ? measuredSum / priorCompletedSum : 1;
  // 仅当至少一段已有实测时，scale 才具备「秒 / 先验占比」的量纲；冷启动下
  // 先验仍是无量纲占比，不能与已跑秒数比大小（否则条一开跑就被拉宽）。
  const calibrated = priorCompletedSum > 0 && measuredSum > 0;

  const startedMs = parseMs(progress?.phase_started_at);
  const currentElapsed = startedMs === null ? null : Math.max((nowMs - startedMs) / 1000, 0);

  const durations: EvalPhaseWeights = {};
  for (const [index, phase] of phases.entries()) {
    const observed = measured[phase];
    if (index < currentIndex && typeof observed === "number" && Number.isFinite(observed)) {
      durations[phase] = Math.max(observed, MIN_PHASE_SECONDS);
      continue;
    }
    const expected = (prior[phase] ?? 0) * scale;
    durations[phase] = index === currentIndex && calibrated && currentElapsed !== null ? Math.max(expected, currentElapsed) : expected;
  }

  const total = phases.reduce((sum, phase) => sum + (durations[phase] ?? 0), 0);
  if (total <= 0) {
    // 防御：无先验也无实测时等分，保证条仍可渲染。
    const even = 1 / phases.length;
    return Object.fromEntries(phases.map((phase) => [phase, even])) as EvalPhaseWeights;
  }
  return Object.fromEntries(phases.map((phase) => [phase, (durations[phase] ?? 0) / total])) as EvalPhaseWeights;
}

/**
 * 加权整体完成度 0..1：已完成段权重和 + 当前段权重 × 段内 done/total。
 * 段内 total 非正（如无 evaluator 且无 judge 的质量段）时该段计 0，不产生 NaN。
 */
export function overallFraction(progress: EvalRunProgress | null | undefined, tier: EvalTier, nowMs: number = Date.now()): number {
  if (!progress) return 0;
  const phases = phasesFor(tier);
  const weights = adaptiveWeights(progress, tier, nowMs);
  const current = currentPhase(progress, phases);

  let completed = 0;
  for (const phase of phases) {
    if (phase === current) break;
    completed += weights[phase] ?? 0;
  }
  const within = progress.total > 0 ? Math.min(1, Math.max(0, progress.done / progress.total)) : 0;
  return Math.min(1, Math.max(0, completed + (weights[current] ?? 0) * within));
}

/**
 * 预计剩余秒数（spec 2026-09-06 §9，2026-09-06 二次修订）：**按段**速率外推，而不是在
 * 整体分数 f 上外推——f 外推会把廉价段（layer1 / 答题前几题）的速率当成全程速率，
 * 早期 ETA 乐观到撒谎（用户实测投诉点）。改为：本段按自身速率推全程时长
 * （phaseFull = elapsed / within），剩余 = phaseFull×(1−within)；其后各段按
 * 「后续段先验占比 / 本段先验占比 × phaseFull」定价，即假设后续段与本段同比例地
 * 贵/便宜。warmup：本段 done>0 且 elapsed ≥ ETA_WARMUP_SECONDS，否则 null
 * （UI 显「估算中…」）；收尾钳到 0，永不负。
 */
export function etaSeconds(progress: EvalRunProgress | null | undefined, tier: EvalTier, nowMs: number = Date.now()): number | null {
  if (!progress) return null;
  const phases = phasesFor(tier);
  const current = currentPhase(progress, phases);
  const within = progress.total > 0 ? Math.min(1, Math.max(0, progress.done / progress.total)) : 0;
  const startedMs = parseMs(progress.phase_started_at);
  const elapsed = startedMs === null ? null : Math.max((nowMs - startedMs) / 1000, 0);
  if (within <= 0 || elapsed === null || elapsed < ETA_WARMUP_SECONDS) return null;

  const phaseFull = elapsed / within;
  const prior = PHASE_WEIGHT_PRIOR[tier];
  const currentPrior = prior[current] ?? 0;
  let future = 0;
  if (currentPrior > 0) {
    for (const phase of phases.slice(phases.indexOf(current) + 1)) future += ((prior[phase] ?? 0) / currentPrior) * phaseFull;
  }
  return Math.max(0, phaseFull * (1 - within) + future);
}

/** ETA 取整到分钟（下限 1）——防抽风跳变；不足一分钟的 ETA 由调用方改用秒粒度。 */
export function etaMinutes(eta: number | null): number | null {
  if (eta === null) return null;
  return Math.max(1, Math.round(eta / 60));
}

/**
 * 在飞那次运行的档位（spec 2026-09-06 §9）：档位单选表达的是「下一次运行」的
 * 选择，不能拿来画当前这次运行的条几何（从题库右键触发的完整档、或刷新后接上
 * 的在飞 run 都会与单选不一致）。phase 已离开 layer1 就必属完整档（快速档没有后
 * 两段）；仍在 layer1 时用触发时记录的档位，两者都无从得知才回退到当前单选。
 */
export function runningTier(progress: EvalRunProgress | null | undefined, triggeredTier: EvalTier | null, selectedTier: EvalTier): EvalTier {
  if (progress && progress.phase !== "layer1") return "l1_l2";
  return triggeredTier ?? selectedTier;
}

// ── 状态槽摘要派生（spec 2026-09-06 §10）─────────────────────

/** 历史行档位：零迁移派生，has_layer2 即完整档（历史行序列化已具备该旗标）。 */
export function tierOfRun(run: EvalRunSummary | null | undefined): EvalTier {
  return run?.has_layer2 ? "l1_l2" : "l1";
}

/** 历史行耗时（秒）；缺戳/倒序（脏数据）→ null——摘要行省掉耗时段而不是显个假数字。 */
export function runDurationSeconds(run: EvalRunSummary | null | undefined): number | null {
  if (!run?.created_at || !run.completed_at) return null;
  const created = Date.parse(run.created_at);
  const completed = Date.parse(run.completed_at);
  if (Number.isNaN(created) || Number.isNaN(completed)) return null;
  const seconds = (completed - created) / 1000;
  return seconds >= 0 ? seconds : null;
}

/** 时长结构件（i18n 中立）：文案由 i18n dur* 键渲染，纯函数不出中文。 */
export type DurationParts = { kind: "seconds"; value: number } | { kind: "minutes"; value: number } | { kind: "minutes-seconds"; minutes: number; seconds: number };

export function durationParts(seconds: number): DurationParts {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return { kind: "seconds", value: total };
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? { kind: "minutes", value: minutes } : { kind: "minutes-seconds", minutes, seconds: rest };
}
