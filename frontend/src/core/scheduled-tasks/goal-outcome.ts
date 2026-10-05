import type { ScheduledTaskRun } from "./types";

export type GoalReasonKey =
  | "missingEvidence"
  | "needsUserInput"
  | "externalWait"
  | "runFailed"
  | "maxContinuations"
  | "noProgress"
  | "tokenCapped"
  | "evaluatorFailed"
  | "noDurableEndOfTurn"
  | "threadChanged"
  | "noVerdict";

// Host-defined codes an `unmet` occurrence stores in `error`. They are the same
// codes the goal-unmet IM notice prints, so unknown codes stay visible verbatim.
const REASON_KEYS: Record<string, GoalReasonKey> = {
  "blocked:missing_evidence": "missingEvidence",
  "blocked:needs_user_input": "needsUserInput",
  "blocked:external_wait": "externalWait",
  "blocked:run_failed": "runFailed",
  max_continuations_reached: "maxContinuations",
  no_progress_detected: "noProgress",
  token_capped: "tokenCapped",
  evaluator_failed: "evaluatorFailed",
  no_durable_end_of_turn: "noDurableEndOfTurn",
  thread_changed_after_evaluation: "threadChanged",
  thread_changed_before_continuation: "threadChanged",
  no_verdict: "noVerdict",
};

export type GoalOutcome =
  | { kind: "met"; reliedOnAssumption: boolean }
  | { kind: "unmet"; code: string | null; reasonKey: GoalReasonKey | null };

/** Goal result of a finished occurrence; null when the run had no goal outcome. */
export function describeGoalOutcome(
  run: Pick<ScheduledTaskRun, "status" | "error" | "goal_verdict">,
): GoalOutcome | null {
  if (run.status === "unmet") {
    const code = run.error ?? null;
    return {
      kind: "unmet",
      code,
      reasonKey: code ? (REASON_KEYS[code] ?? null) : null,
    };
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
