import { expect, test } from "@rstest/core";

import {
  describeGoalOutcome,
  requestedScheduleStop,
} from "@/core/scheduled-tasks/goal-outcome";
import type { ScheduledTaskRun } from "@/core/scheduled-tasks/types";

type OutcomeInput = Pick<ScheduledTaskRun, "status" | "error" | "goal_verdict">;

const run = (overrides: Partial<OutcomeInput>): OutcomeInput => ({
  status: "success",
  error: null,
  ...overrides,
});

test("a run without a goal verdict has no goal outcome", () => {
  expect(describeGoalOutcome(run({}))).toBeNull();
  expect(describeGoalOutcome(run({ goal_verdict: null }))).toBeNull();
  expect(
    describeGoalOutcome(run({ status: "failed", error: "boom" })),
  ).toBeNull();
});

test("a satisfied verdict is met, with the assumption flag kept", () => {
  expect(
    describeGoalOutcome(run({ goal_verdict: { satisfied: true } })),
  ).toEqual({ kind: "met", reliedOnAssumption: false });
  expect(
    describeGoalOutcome(
      run({
        goal_verdict: { satisfied: true, relied_on_assumption: true },
      }),
    ),
  ).toEqual({ kind: "met", reliedOnAssumption: true });
});

test("a success with an unsatisfied verdict is not reported as met", () => {
  expect(
    describeGoalOutcome(run({ goal_verdict: { satisfied: false } })),
  ).toBeNull();
});

test.each([
  ["blocked:missing_evidence", "missingEvidence"],
  ["blocked:needs_user_input", "needsUserInput"],
  ["blocked:external_wait", "externalWait"],
  ["blocked:run_failed", "runFailed"],
  ["max_continuations_reached", "maxContinuations"],
  ["no_progress_detected", "noProgress"],
  ["token_capped", "tokenCapped"],
  ["evaluator_failed", "evaluatorFailed"],
  ["no_durable_end_of_turn", "noDurableEndOfTurn"],
  ["thread_changed_after_evaluation", "threadChanged"],
  ["thread_changed_before_continuation", "threadChanged"],
  ["no_verdict", "noVerdict"],
])("unmet reason %s maps to %s", (code, reasonKey) => {
  expect(describeGoalOutcome(run({ status: "unmet", error: code }))).toEqual({
    kind: "unmet",
    code,
    reasonKey,
  });
});

test("an unknown unmet code stays visible without a label", () => {
  expect(
    describeGoalOutcome(run({ status: "unmet", error: "future_reason" })),
  ).toEqual({ kind: "unmet", code: "future_reason", reasonKey: null });
  expect(describeGoalOutcome(run({ status: "unmet", error: null }))).toEqual({
    kind: "unmet",
    code: null,
    reasonKey: null,
  });
});

test.each([
  ["run-2", "run-2", true],
  ["run-2", "run-1", false],
  ["run-2", null, false],
  [null, null, false],
])(
  "run %s with stop request %s reports a stop request: %s",
  (runId, stopRequestedRunId, expected) => {
    expect(
      requestedScheduleStop({
        run_id: runId,
        stop_requested_run_id: stopRequestedRunId,
      }),
    ).toBe(expected);
  },
);
