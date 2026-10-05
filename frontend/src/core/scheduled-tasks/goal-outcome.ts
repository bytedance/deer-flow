import type { ScheduledTaskRun } from "./types";

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

function reasonKeyOf(code: string): GoalReasonKey | null {
  return REASON_KEYS[code.replace(/^blocked:/, "")] ?? null;
}

export type GoalOutcome =
  | { kind: "met"; reliedOnAssumption: boolean }
  | { kind: "unmet"; code: string | null; reasonKey: GoalReasonKey | null };

/** Goal result of a finished occurrence; null when the run had no goal outcome. */
export function describeGoalOutcome(
  run: Pick<ScheduledTaskRun, "status" | "error" | "goal_verdict">,
): GoalOutcome | null {
  if (run.status === "unmet") {
    const code = run.error ?? null;
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
