import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@rstest/core";

import {
  agentStopTime,
  CHECK_FAILURE_CODES,
  describeGoalOutcome,
  describeTaskLastError,
  describeTaskOutcome,
  parseStopRunId,
  requestedScheduleStop,
} from "@/core/scheduled-tasks/goal-outcome";
import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";

type OutcomeInput = Pick<ScheduledTaskRun, "status" | "error" | "goal_verdict">;

type ContractFile = {
  version: number;
  agent_stop_last_error_prefix: string;
  auto_pause_last_error: string;
  unmet_reason_codes: string[];
  check_failure_codes: string[];
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

test.each([
  ["evaluator_failed", "evaluatorFailed"],
  ["no_durable_end_of_turn", "noDurableEndOfTurn"],
  ["thread_changed_after_evaluation", "threadChanged"],
  ["thread_changed_before_continuation", "threadChanged"],
])(
  "a goal check that could not run (%s) is unchecked, not a miss",
  (code, reasonKey) => {
    expect(describeGoalOutcome(run({ status: "unmet", error: code }))).toEqual({
      kind: "unchecked",
      code,
      reasonKey,
    });
  },
);

test("contract v2 pins the check-failure codes the UI treats as unchecked", () => {
  expect(CONTRACT.version).toBe(2);
  expect([...CHECK_FAILURE_CODES].sort()).toEqual(
    [...CONTRACT.check_failure_codes].sort(),
  );
});

test("every contract reason code has a label in run history and task detail", () => {
  for (const code of CONTRACT.unmet_reason_codes) {
    const outcome = describeGoalOutcome(run({ status: "unmet", error: code }));
    const expectedKind = CONTRACT.check_failure_codes.includes(code)
      ? "unchecked"
      : "unmet";
    expect(outcome?.kind).toBe(expectedKind);
    expect(
      outcome && outcome.kind !== "met" ? outcome.reasonKey : null,
    ).not.toBeNull();
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

test("parseStopRunId reads the run id of an agent stop", () => {
  expect(parseStopRunId(`${CONTRACT.agent_stop_last_error_prefix}run-7`)).toBe(
    "run-7",
  );
  expect(parseStopRunId(CONTRACT.auto_pause_last_error)).toBeNull();
  expect(parseStopRunId(null)).toBeNull();
  expect(
    parseStopRunId(`${CONTRACT.agent_stop_last_error_prefix}a b`),
  ).toBeNull();
});

type OutcomeTask = Parameters<typeof describeTaskOutcome>[0];

const outcomeTask = (overrides: Partial<ScheduledTask>): OutcomeTask => ({
  status: "enabled",
  schedule_type: "cron",
  last_error: null,
  last_run_at: null,
  last_run_id: null,
  max_runs: null,
  end_at: null,
  automatic_runs_used: 0,
  ...overrides,
});

const historyRun = (overrides: Partial<ScheduledTaskRun>): ScheduledTaskRun =>
  ({
    id: "occ",
    task_id: "task-1",
    thread_id: "thread-x",
    run_id: "run-x",
    scheduled_for: "2026-10-06T01:00:00+00:00",
    trigger: "scheduled",
    status: "success",
    error: null,
    attempt_count: 1,
    started_at: null,
    finished_at: null,
    created_at: "2026-10-06T01:00:00+00:00",
    ...overrides,
  }) as ScheduledTaskRun;

test("describeTaskOutcome: agent stop links the run that asked to stop", () => {
  const runs = [
    historyRun({ id: "occ-3", run_id: "run-3", thread_id: "thread-3" }),
    historyRun({
      id: "occ-2",
      run_id: "run-2",
      thread_id: "thread-2",
      started_at: "2026-10-05T01:00:30+00:00",
      finished_at: "2026-10-05T01:05:00+00:00",
    }),
  ];
  expect(
    describeTaskOutcome(
      outcomeTask({
        status: "paused",
        last_error: `${CONTRACT.agent_stop_last_error_prefix}run-2`,
      }),
      runs,
    ),
  ).toEqual({
    kind: "pausedByAgent",
    runThreadId: "thread-2",
    at: "2026-10-05T01:00:30+00:00",
  });
  // The stopping run is on an older page: no link, the task's last launch
  // time while that launch is the stopping run.
  expect(
    describeTaskOutcome(
      outcomeTask({
        status: "paused",
        last_error: `${CONTRACT.agent_stop_last_error_prefix}run-1`,
        last_run_id: "run-1",
        last_run_at: "2026-10-04T01:00:00+00:00",
      }),
      runs,
    ),
  ).toEqual({
    kind: "pausedByAgent",
    runThreadId: null,
    at: "2026-10-04T01:00:00+00:00",
  });
});

test("describeTaskOutcome: an earlier stop on the page shown never stands in for this pause", () => {
  // Resumed after run-old stopped it, then stopped again by run-current; the
  // page shown is older and holds only the first stop.
  const olderPage = [
    historyRun({
      id: "occ-old",
      run_id: "run-old",
      thread_id: "thread-old",
      stop_requested_run_id: "run-old",
      started_at: "2026-10-01T01:00:30+00:00",
    }),
  ];
  expect(
    describeTaskOutcome(
      outcomeTask({
        status: "paused",
        last_error: `${CONTRACT.agent_stop_last_error_prefix}run-current`,
        last_run_id: "run-current",
        last_run_at: "2026-10-05T01:00:00+00:00",
      }),
      olderPage,
    ),
  ).toEqual({
    kind: "pausedByAgent",
    runThreadId: null,
    at: "2026-10-05T01:00:00+00:00",
  });
});

test("agentStopTime: a trial after the agent paused the task never lends its time", () => {
  const stopped = {
    last_error: `${CONTRACT.agent_stop_last_error_prefix}run-1`,
    last_run_id: "run-1",
    last_run_at: "2026-10-04T01:00:00+00:00",
  };
  expect(agentStopTime(stopped)).toBe("2026-10-04T01:00:00+00:00");
  // "Run once now" on the paused task moves last_run_id / last_run_at.
  const afterTrial = {
    ...stopped,
    last_run_id: "run-trial",
    last_run_at: "2026-10-05T08:00:00+00:00",
  };
  expect(agentStopTime(afterTrial)).toBeNull();
  expect(
    describeTaskOutcome(
      outcomeTask({ status: "paused", schedule_type: "cron", ...afterTrial }),
      [],
    ),
  ).toEqual({ kind: "pausedByAgent", runThreadId: null, at: null });
});

test("describeTaskOutcome: auto-pause reports the latest unmet scheduled run", () => {
  const runs = [
    historyRun({
      id: "trial",
      trigger: "manual",
      status: "unmet",
      error: "no_verdict",
    }),
    historyRun({
      id: "occ-3",
      status: "unmet",
      error: "blocked:missing_evidence",
      thread_id: "thread-3",
      summary: "清单里还有 2 项没勾",
    }),
    historyRun({ id: "occ-2", status: "unmet", error: "no_verdict" }),
  ];
  expect(
    describeTaskOutcome(
      outcomeTask({
        status: "paused",
        last_error: CONTRACT.auto_pause_last_error,
      }),
      runs,
    ),
  ).toEqual({
    kind: "autoPaused",
    latestReasonKey: "missingEvidence",
    latestThreadId: "thread-3",
    latestSummary: "清单里还有 2 项没勾",
  });
});

test("describeTaskOutcome: a plain pause has no notice", () => {
  expect(describeTaskOutcome(outcomeTask({ status: "paused" }), [])).toBeNull();
  expect(describeTaskOutcome(outcomeTask({}), [])).toBeNull();
});

test("describeTaskOutcome: finished by the run limit or the end time", () => {
  expect(
    describeTaskOutcome(
      outcomeTask({ status: "completed", max_runs: 5, automatic_runs_used: 5 }),
      [],
    ),
  ).toEqual({ kind: "limitReached", used: 5, max: 5 });
  expect(
    describeTaskOutcome(
      outcomeTask({
        status: "completed",
        max_runs: 10,
        automatic_runs_used: 3,
        end_at: "2026-10-01T10:00:00+00:00",
      }),
      [],
      new Date("2026-10-06T00:00:00Z"),
    ),
  ).toEqual({ kind: "endReached", endAt: "2026-10-01T10:00:00+00:00" });
  expect(
    describeTaskOutcome(
      outcomeTask({ status: "completed", end_at: "2026-12-01T10:00:00+00:00" }),
      [],
      new Date("2026-10-06T00:00:00Z"),
    ),
  ).toBeNull();
});

test("describeTaskOutcome: one-time tasks", () => {
  expect(
    describeTaskOutcome(
      outcomeTask({ status: "completed", schedule_type: "once" }),
      [],
    ),
  ).toEqual({ kind: "onceFinished" });
  expect(
    describeTaskOutcome(
      outcomeTask({ status: "failed", schedule_type: "once" }),
      [],
    ),
  ).toEqual({ kind: "onceFailed" });
});
