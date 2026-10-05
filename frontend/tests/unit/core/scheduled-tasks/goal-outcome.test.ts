import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@rstest/core";

import {
  describeGoalOutcome,
  describeTaskLastError,
  requestedScheduleStop,
} from "@/core/scheduled-tasks/goal-outcome";
import type { ScheduledTaskRun } from "@/core/scheduled-tasks/types";

type OutcomeInput = Pick<ScheduledTaskRun, "status" | "error" | "goal_verdict">;

type ContractFile = {
  agent_stop_last_error_prefix: string;
  auto_pause_last_error: string;
  unmet_reason_codes: string[];
};

const CONTRACT = JSON.parse(
  readFileSync(
    resolve(
      __dirname,
      "../../../../../contracts/scheduled_goal_notes_contract.json",
    ),
    "utf-8",
  ),
) as ContractFile;

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
  ["blocked:goal_not_met_yet", "goalNotMetYet"],
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

test.each([
  [
    "stopped by the agent in run 3f2a9c1e-8b47-4d2a-9e61-5c0b7a1d4e93",
    { kind: "agentStop" },
  ],
  ["paused after 3 unmet scheduled goal runs", { kind: "autoPause" }],
  [
    "blocked:missing_evidence",
    { kind: "goalUnmet", reasonKey: "missingEvidence" },
  ],
  ["no_verdict", { kind: "goalUnmet", reasonKey: "noVerdict" }],
])("host-written last_error %s is recognized", (lastError, expected) => {
  expect(describeTaskLastError(lastError)).toEqual(expected);
});

test.each([
  [null],
  [""],
  ["Connection reset by peer"],
  ["stopped by the agent in run "],
  ["Paused after 3 unmet scheduled goal runs"],
  ["stopped by the agent in run abc; then failed"],
])("other last_error %s stays a plain error message", (lastError) => {
  expect(describeTaskLastError(lastError)).toBeNull();
});

test("every contract reason code has a label in run history and task detail", () => {
  for (const code of CONTRACT.unmet_reason_codes) {
    const outcome = describeGoalOutcome(run({ status: "unmet", error: code }));
    expect(outcome?.kind).toBe("unmet");
    expect(outcome?.kind === "unmet" ? outcome.reasonKey : null).not.toBeNull();
    expect(describeTaskLastError(code)?.kind).toBe("goalUnmet");
  }
});

test("contract last_error strings are recognized", () => {
  expect(
    describeTaskLastError(
      `${CONTRACT.agent_stop_last_error_prefix}3f2a9c1e-8b47-4d2a-9e61-5c0b7a1d4e93`,
    ),
  ).toEqual({ kind: "agentStop" });
  expect(describeTaskLastError(CONTRACT.auto_pause_last_error)).toEqual({
    kind: "autoPause",
  });
});
