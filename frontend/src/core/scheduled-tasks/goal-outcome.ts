import type { ScheduledTask, ScheduledTaskRun } from "./types";

export type GoalReasonKey =
  | "missingEvidence"
  | "needsUserInput"
  | "externalWait"
  | "runFailed"
  | "goalNotMetYet"
  | "maxContinuations"
  | "noProgress"
  | "tokenCapped"
  | "evaluatorFailed"
  | "noDurableEndOfTurn"
  | "threadChanged"
  | "noVerdict";

// Host-defined codes an `unmet` occurrence stores in `error`, keyed without
// the `blocked:` prefix like the IM notice map (`_GOAL_REASON_TEXT`).
// contracts/scheduled_goal_notes_contract.json pins the codes the backend
// writes; unknown codes stay visible verbatim.
const REASON_KEYS: Record<string, GoalReasonKey> = {
  missing_evidence: "missingEvidence",
  needs_user_input: "needsUserInput",
  external_wait: "externalWait",
  run_failed: "runFailed",
  goal_not_met_yet: "goalNotMetYet",
  max_continuations_reached: "maxContinuations",
  no_progress_detected: "noProgress",
  token_capped: "tokenCapped",
  evaluator_failed: "evaluatorFailed",
  no_durable_end_of_turn: "noDurableEndOfTurn",
  thread_changed_after_evaluation: "threadChanged",
  thread_changed_before_continuation: "threadChanged",
  no_verdict: "noVerdict",
};

// Host-written task `last_error` values, pinned by the same contract.
const AGENT_STOP_LAST_ERROR_PREFIX = "stopped by the agent in run ";
const AUTO_PAUSE_LAST_ERROR = "paused after 3 unmet scheduled goal runs";

/**
 * Codes for a goal check that could not run (contract `check_failure_codes`).
 * The host neither counts them as a miss nor resets the miss streak, so the
 * UI shows "Couldn't check the goal" instead of "Goal not met".
 */
export const CHECK_FAILURE_CODES: readonly string[] = [
  "evaluator_failed",
  "no_durable_end_of_turn",
  "thread_changed_after_evaluation",
  "thread_changed_before_continuation",
];

function reasonKeyOf(code: string): GoalReasonKey | null {
  return REASON_KEYS[code.replace(/^blocked:/, "")] ?? null;
}

export type GoalOutcome =
  | { kind: "met"; reliedOnAssumption: boolean }
  | { kind: "unmet"; code: string | null; reasonKey: GoalReasonKey | null }
  | { kind: "unchecked"; code: string; reasonKey: GoalReasonKey | null };

/** Goal result of a finished occurrence; null when the run had no goal outcome. */
export function describeGoalOutcome(
  run: Pick<ScheduledTaskRun, "status" | "error" | "goal_verdict">,
): GoalOutcome | null {
  if (run.status === "unmet") {
    const code = run.error ?? null;
    if (code && CHECK_FAILURE_CODES.includes(code)) {
      return { kind: "unchecked", code, reasonKey: reasonKeyOf(code) };
    }
    return { kind: "unmet", code, reasonKey: code ? reasonKeyOf(code) : null };
  }
  if (run.status === "success" && run.goal_verdict?.satisfied === true) {
    return {
      kind: "met",
      reliedOnAssumption: run.goal_verdict.relied_on_assumption === true,
    };
  }
  return null;
}

/** True for the occurrence whose agent asked to stop its own schedule. */
export function requestedScheduleStop(
  run: Pick<ScheduledTaskRun, "run_id" | "stop_requested_run_id">,
): boolean {
  return Boolean(run.run_id) && run.stop_requested_run_id === run.run_id;
}

export type TaskLastNote =
  | { kind: "agentStop" }
  | { kind: "autoPause" }
  | { kind: "goalUnmet"; reasonKey: GoalReasonKey };

/**
 * Recognize the host-written `last_error` values from goal and stop
 * finalization (backend `scheduled_task_runs/finalization.py`). Anything else
 * is a real error message and returns null.
 */
export function describeTaskLastError(
  lastError: string | null,
): TaskLastNote | null {
  if (!lastError) {
    return null;
  }
  if (
    lastError.startsWith(AGENT_STOP_LAST_ERROR_PREFIX) &&
    /^\S+$/.test(lastError.slice(AGENT_STOP_LAST_ERROR_PREFIX.length))
  ) {
    return { kind: "agentStop" };
  }
  if (lastError === AUTO_PAUSE_LAST_ERROR) {
    return { kind: "autoPause" };
  }
  const reasonKey = reasonKeyOf(lastError);
  return reasonKey ? { kind: "goalUnmet", reasonKey } : null;
}

/** The run id in an agent-stop `last_error` ("stopped by the agent in run <id>"), else null. */
export function parseStopRunId(lastError: string | null): string | null {
  if (!lastError?.startsWith(AGENT_STOP_LAST_ERROR_PREFIX)) {
    return null;
  }
  const runId = lastError.slice(AGENT_STOP_LAST_ERROR_PREFIX.length);
  return /^\S+$/.test(runId) ? runId : null;
}

/**
 * When the run that paused the task started: that run's start (or slot) when
 * it is at hand, else the task's last launch time, but only while that launch
 * is the stopping run (a later trial moves `last_run_at`). Null when unknown,
 * so no view shows another run's time as the moment the agent paused it.
 * Every view uses this one source (list line, card, notice, "Reached").
 */
export function agentStopTime(
  task: Pick<ScheduledTask, "last_error" | "last_run_at" | "last_run_id">,
  run?: Pick<ScheduledTaskRun, "started_at" | "scheduled_for"> | null,
): string | null {
  if (run) {
    return run.started_at ?? run.scheduled_for ?? null;
  }
  const stopRunId = parseStopRunId(task.last_error);
  return stopRunId !== null && stopRunId === task.last_run_id
    ? task.last_run_at
    : null;
}

/**
 * Why a task stopped running, derived on read from task and run state (the
 * host writes no separate notice):
 * - pausedByAgent: a run asked to stop its own schedule; `runThreadId` is that
 *   run's chat when the run is among `runs`.
 * - autoPaused: three scheduled runs in a row missed the goal; the latest
 *   unmet run gives the reason and its chat.
 * - limitReached / endReached: a finished task whose safety cap ran out.
 * - onceFinished / onceFailed: a one-time task that ran or failed.
 * `runs` are newest first (the run history order).
 */
export type TaskOutcome =
  | { kind: "pausedByAgent"; runThreadId: string | null; at: string | null }
  | {
      kind: "autoPaused";
      latestReasonKey: GoalReasonKey | null;
      latestThreadId: string | null;
      /** The agent's own summary of that run, in the user's language. */
      latestSummary: string | null;
    }
  | { kind: "limitReached"; used: number; max: number }
  | { kind: "endReached"; endAt: string }
  | { kind: "onceFinished" }
  | { kind: "onceFailed" };

export function describeTaskOutcome(
  task: Pick<
    ScheduledTask,
    | "status"
    | "schedule_type"
    | "last_error"
    | "last_run_at"
    | "last_run_id"
    | "max_runs"
    | "end_at"
    | "automatic_runs_used"
  >,
  runs: readonly ScheduledTaskRun[],
  now: Date = new Date(),
): TaskOutcome | null {
  if (task.status === "paused") {
    const note = describeTaskLastError(task.last_error);
    if (note?.kind === "agentStop") {
      const stopRunId = parseStopRunId(task.last_error);
      const run =
        runs.find((item) => stopRunId !== null && item.run_id === stopRunId) ??
        runs.find(requestedScheduleStop) ??
        null;
      return {
        kind: "pausedByAgent",
        runThreadId: run?.thread_id ?? null,
        at: agentStopTime(task, run),
      };
    }
    if (note?.kind === "autoPause") {
      const latest = runs.find(
        (run) => run.trigger === "scheduled" && run.status === "unmet",
      );
      return {
        kind: "autoPaused",
        latestReasonKey: latest?.error ? reasonKeyOf(latest.error) : null,
        latestThreadId: latest?.thread_id ?? null,
        latestSummary: latest?.summary ?? null,
      };
    }
    return null;
  }
  if (task.schedule_type === "once") {
    if (task.status === "completed") return { kind: "onceFinished" };
    if (task.status === "failed") return { kind: "onceFailed" };
    return null;
  }
  if (task.status !== "completed") {
    return null;
  }
  const used = task.automatic_runs_used ?? 0;
  if (typeof task.max_runs === "number" && used >= task.max_runs) {
    return { kind: "limitReached", used, max: task.max_runs };
  }
  if (task.end_at) {
    const endAt = new Date(task.end_at);
    if (!Number.isNaN(endAt.getTime()) && endAt.getTime() <= now.getTime()) {
      return { kind: "endReached", endAt: task.end_at };
    }
  }
  return null;
}
