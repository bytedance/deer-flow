import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  describeGoalBar,
  GOAL_HOST_REASON_TEXTS,
  goalBarAnnounceKey,
  goalOutcomeKey,
  goalReconciliationKey,
  isGoalOutcomeCurrent,
  isThreadGoalOutcome,
  sameGoalInstance,
} from "@/components/workspace/goal-status-helpers";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

function makeGoal(overrides: Partial<GoalState> = {}): GoalState {
  return {
    objective: "ship it",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    continuation_count: 0,
    max_continuations: 8,
    no_progress_count: 0,
    max_no_progress_continuations: 2,
    ...overrides,
  };
}

function stoodDown(
  code: string,
  overrides: Partial<GoalState> = {},
  reason = "The report has no totals yet.",
): GoalState {
  return makeGoal({
    updated_at: "2026-01-01T00:05:00Z",
    ...overrides,
    last_evaluation: {
      satisfied: false,
      blocker: "goal_not_met_yet",
      reason,
      stand_down_reason: code,
    },
  });
}

function makeOutcome(
  overrides: Partial<ThreadGoalOutcome> = {},
): ThreadGoalOutcome {
  return {
    status: "achieved",
    objective: "ship it",
    goal_created_at: "2026-01-01T00:00:00Z",
    achieved_at: "2026-01-01T00:09:00Z",
    continuation_count: 1,
    max_continuations: 8,
    reason: "The report lists every total.",
    relied_on_assumption: false,
    reply_message_id: "ai-2",
    ...overrides,
  };
}

const idle = (goal: GoalState | null, hasOpenHumanInputCard = false) =>
  describeGoalBar({
    goal,
    outcome: null,
    isRunning: false,
    hasOpenHumanInputCard,
  });

describe("describeGoalBar", () => {
  it("shows a fresh goal as set while idle and in progress while running", () => {
    const goal = makeGoal();
    expect(idle(goal)).toEqual({ kind: "set", goal });
    expect(describeGoalBar({ goal, outcome: null, isRunning: true })).toEqual({
      kind: "inProgress",
      goal,
    });
  });

  it("counts automatic follow-ups while one is running", () => {
    const goal = makeGoal({
      continuation_count: 1,
      last_evaluation: {
        satisfied: false,
        blocker: "goal_not_met_yet",
        reason: "Totals missing.",
      },
    });
    expect(describeGoalBar({ goal, outcome: null, isRunning: true })).toEqual({
      kind: "continuing",
      goal,
      count: 1,
      max: 8,
    });
    // A stored satisfied verdict is no reason to continue.
    const satisfied = makeGoal({
      continuation_count: 1,
      last_evaluation: { satisfied: true, blocker: "none", reason: "Done." },
    });
    expect(
      describeGoalBar({ goal: satisfied, outcome: null, isRunning: true }),
    ).toEqual({ kind: "inProgress", goal: satisfied });
  });

  it("hides a reason left by an earlier run while a new run streams", () => {
    const goal = stoodDown("max_continuations_reached", {
      continuation_count: 8,
    });
    expect(describeGoalBar({ goal, outcome: null, isRunning: true })).toEqual({
      kind: "inProgress",
      goal,
    });
  });

  it("reads 8/8 with a stand-down as stopped at the limit, never Continuing", () => {
    expect(
      idle(stoodDown("max_continuations_reached", { continuation_count: 8 })),
    ).toMatchObject({
      kind: "stopped",
      stop: "limit",
      chip: "stopped",
      reasonKey: "maxContinuations",
      count: 8,
      max: 8,
      note: "The report has no totals yet.",
      rawCode: null,
    });
  });

  it.each([
    [
      "max_continuations_reached",
      { max_continuations: 0 },
      "autoOff",
      "stopped",
    ],
    ["no_progress_detected", {}, "noProgress", "stopped"],
    ["token_capped", {}, "tokenCapped", "stopped"],
    ["blocked:missing_evidence", {}, "missingEvidence", "stopped"],
    ["blocked:run_failed", {}, "runFailed", "stopped"],
    ["blocked:external_wait", {}, "external", "waiting"],
  ] as const)("maps %s to its stop row", (code, overrides, stop, chip) => {
    expect(idle(stoodDown(code, overrides))).toMatchObject({
      kind: "stopped",
      stop,
      chip,
      rawCode: null,
    });
  });

  it("tells a count-0 stand-down apart from a fresh goal", () => {
    const fresh = idle(makeGoal());
    const stopped = idle(stoodDown("blocked:missing_evidence"));
    expect(fresh.kind).toBe("set");
    expect(stopped).toMatchObject({ kind: "stopped", count: 0 });
  });

  it("asks for the open question only when a card is open", () => {
    const goal = stoodDown(
      "blocked:needs_user_input",
      {},
      "The turn ended on a question to the user that has not been answered.",
    );
    expect(idle(goal, true)).toMatchObject({
      stop: "needsInputCard",
      chip: "waitingForYou",
      // Host-written, so never shown as the checker's note.
      note: null,
    });
    expect(
      idle(stoodDown("blocked:needs_user_input", {}, "It guessed the year.")),
    ).toMatchObject({
      stop: "needsInputReply",
      chip: "waitingForYou",
      note: "It guessed the year.",
    });
  });

  it.each([
    "evaluator_failed",
    "no_durable_end_of_turn",
    "thread_changed_after_evaluation",
    "thread_changed_before_continuation",
  ])("shows %s as unchecked with no evaluator note", (code) => {
    expect(idle(stoodDown(code))).toMatchObject({
      kind: "stopped",
      stop: "unchecked",
      chip: "unchecked",
      note: null,
      rawCode: null,
    });
  });

  it("keeps a stored satisfied verdict unchecked when the chat changed", () => {
    const goal = makeGoal({
      last_evaluation: {
        satisfied: true,
        blocker: "none",
        reason: "Done.",
        stand_down_reason: "thread_changed_after_evaluation",
      },
    });
    expect(idle(goal)).toMatchObject({ stop: "unchecked", note: null });
  });

  it("keeps an unknown code only for Details", () => {
    expect(idle(stoodDown("blocked:new_reason"))).toMatchObject({
      stop: "unknown",
      chip: "stopped",
      reasonKey: null,
      rawCode: "blocked:new_reason",
    });
    // A known label key that is not a chat stand-down is still unknown.
    expect(idle(stoodDown("blocked:goal_not_met_yet"))).toMatchObject({
      stop: "unknown",
      rawCode: "blocked:goal_not_met_yet",
    });
  });

  it("shows a run that ended after an automatic follow-up as paused", () => {
    const goal = makeGoal({
      continuation_count: 2,
      last_evaluation: {
        satisfied: false,
        blocker: "goal_not_met_yet",
        reason: "Totals missing.",
      },
    });
    // No checker note: a skipped clear leaves the earlier unmet verdict.
    expect(idle(goal)).toEqual({ kind: "paused", goal, count: 2, max: 8 });
    expect(idle({ ...goal, continuation_count: 0 }).kind).toBe("set");
  });

  it("shows a current record as met when no goal is active", () => {
    const outcome = makeOutcome({ continuation_count: 3 });
    expect(describeGoalBar({ goal: null, outcome, isRunning: false })).toEqual({
      kind: "met",
      outcome,
      count: 3,
      max: 8,
      reliedOnAssumption: false,
      note: "The report lists every total.",
    });
    expect(
      describeGoalBar({
        goal: null,
        outcome: makeOutcome({ relied_on_assumption: true }),
        isRunning: true,
      }),
    ).toMatchObject({ kind: "met", reliedOnAssumption: true });
  });

  it("lets an active goal win over a record", () => {
    const goal = makeGoal({ objective: "next" });
    expect(
      describeGoalBar({ goal, outcome: makeOutcome(), isRunning: false }),
    ).toEqual({ kind: "set", goal });
  });

  it("renders nothing without a goal or a record", () => {
    expect(idle(null)).toEqual({ kind: "none" });
  });

  it("never treats host-written reasons as the checker's note", () => {
    for (const reason of GOAL_HOST_REASON_TEXTS) {
      expect(
        idle(stoodDown("blocked:missing_evidence", {}, reason)),
      ).toMatchObject({ note: null });
    }
  });
});

describe("goalBarAnnounceKey", () => {
  it("stays put while the counter rises and changes with the state", () => {
    const running = (count: number) =>
      describeGoalBar({
        goal: makeGoal({ continuation_count: count }),
        outcome: null,
        isRunning: true,
      });
    expect(goalBarAnnounceKey(running(1))).toBe(goalBarAnnounceKey(running(2)));
    expect(goalBarAnnounceKey(running(0))).toBe("");
    expect(goalBarAnnounceKey(idle(makeGoal()))).toBe("");
    expect(goalBarAnnounceKey(idle(stoodDown("token_capped")))).not.toBe(
      goalBarAnnounceKey(idle(stoodDown("no_progress_detected"))),
    );
  });

  it("changes for the same state of another goal", () => {
    const key = (overrides: Partial<GoalState>) =>
      goalBarAnnounceKey(idle(stoodDown("token_capped", overrides)));
    expect(key({})).toBe(key({ updated_at: "2026-01-01T00:07:00Z" }));
    expect(key({})).not.toBe(key({ created_at: "2026-01-02T00:00:00Z" }));
    expect(key({})).not.toBe(key({ objective: "other" }));

    const paused = (overrides: Partial<GoalState>) =>
      goalBarAnnounceKey(
        idle(
          makeGoal({
            continuation_count: 2,
            last_evaluation: {
              satisfied: false,
              blocker: "goal_not_met_yet",
              reason: "Totals missing.",
            },
            ...overrides,
          }),
        ),
      );
    expect(paused({})).toBe(paused({ continuation_count: 3 }));
    expect(paused({})).not.toBe(paused({ objective: "other" }));
    expect(paused({})).not.toBe(paused({ created_at: "2026-01-02T00:00:00Z" }));

    const met = (outcome: ThreadGoalOutcome) =>
      goalBarAnnounceKey(
        describeGoalBar({ goal: null, outcome, isRunning: false }),
      );
    expect(met(makeOutcome())).toBe(met(makeOutcome()));
    expect(met(makeOutcome())).not.toBe(
      met(makeOutcome({ achieved_at: "2026-01-01T00:10:00Z" })),
    );
  });
});

function human(id: string, extra: Partial<Message> = {}): Message {
  return { id, type: "human", content: "next please", ...extra } as Message;
}

function ai(id: string, content: Message["content"], extra = {}): Message {
  return { id, type: "ai", content, ...extra } as Message;
}

describe("isGoalOutcomeCurrent", () => {
  const anchor = ai("ai-2", "Here is the report.");
  const outcome = makeOutcome({ reply_message_id: "ai-2" });

  it.each([
    ["the anchor is the last message", [human("h-1"), anchor], true],
    ["a visible human message follows", [anchor, human("h-2")], false],
    ["a visible AI reply follows", [anchor, ai("ai-3", "More.")], false],
    [
      "only a hidden human message follows",
      [anchor, human("h-2", { additional_kwargs: { hide_from_ui: true } })],
      true,
    ],
    [
      "an AI message with tool calls and no text follows",
      [
        anchor,
        ai("ai-3", "", {
          tool_calls: [{ id: "call-1", name: "present_files", args: {} }],
        }),
        {
          id: "tool-1",
          type: "tool",
          content: "ok",
          tool_call_id: "call-1",
        } as Message,
      ],
      true,
    ],
    [
      "an empty final AI message follows",
      [anchor, ai("ai-3", [{ type: "text", text: "  " }])],
      true,
    ],
    ["the anchor is gone (regenerated)", [human("h-1")], false],
    [
      "the anchor is not among the loaded messages",
      [human("h-0", { additional_kwargs: { hide_from_ui: true } })],
      false,
    ],
  ] as const)("%s", (_case, messages, current) => {
    expect(isGoalOutcomeCurrent(outcome, messages)).toBe(current);
  });

  it("is never current without an anchor", () => {
    expect(
      isGoalOutcomeCurrent(makeOutcome({ reply_message_id: null }), [anchor]),
    ).toBe(false);
  });
});

describe("goal outcome identity", () => {
  it("accepts only achieved records with their identity fields", () => {
    expect(isThreadGoalOutcome(makeOutcome())).toBe(true);
    expect(isThreadGoalOutcome({ ...makeOutcome(), goal_created_at: "" })).toBe(
      true,
    );
    expect(isThreadGoalOutcome({ ...makeOutcome(), status: "cleared" })).toBe(
      false,
    );
    expect(
      isThreadGoalOutcome({ ...makeOutcome(), objective: undefined }),
    ).toBe(false);
    expect(
      isThreadGoalOutcome({ ...makeOutcome(), goal_created_at: undefined }),
    ).toBe(false);
    expect(isThreadGoalOutcome(null)).toBe(false);
    expect(isThreadGoalOutcome([makeOutcome()])).toBe(false);
  });

  it("matches a record to its own goal, not a later one with the same text", () => {
    const goal = makeGoal();
    expect(sameGoalInstance(goal, makeOutcome())).toBe(true);
    expect(
      sameGoalInstance(
        makeGoal({ created_at: "2026-01-02T00:00:00Z" }),
        makeOutcome(),
      ),
    ).toBe(false);
    expect(
      sameGoalInstance(makeGoal({ objective: "other" }), makeOutcome()),
    ).toBe(false);
  });

  it("matches a goal stored without created_at to its '' record", () => {
    // A status read keeps such a goal; the backend records it with "".
    const goal = { objective: "ship it" } as GoalState;
    expect(sameGoalInstance(goal, makeOutcome({ goal_created_at: "" }))).toBe(
      true,
    );
    expect(sameGoalInstance(goal, makeOutcome())).toBe(false);
  });

  it("keys a later record of the same goal differently", () => {
    expect(goalOutcomeKey(null)).toBe("none");
    expect(goalOutcomeKey(makeOutcome())).not.toBe(
      goalOutcomeKey(makeOutcome({ achieved_at: "2026-01-01T00:10:00Z" })),
    );
  });
});

describe("goalReconciliationKey", () => {
  it("returns a constant sentinel when there is no goal", () => {
    expect(goalReconciliationKey(null)).toBe("none");
  });

  it("is stable for an unchanged goal", () => {
    expect(goalReconciliationKey(makeGoal())).toBe(
      goalReconciliationKey(makeGoal()),
    );
  });

  it("changes when the agent auto-continues", () => {
    expect(goalReconciliationKey(makeGoal({ continuation_count: 0 }))).not.toBe(
      goalReconciliationKey(
        makeGoal({
          continuation_count: 1,
          updated_at: "2026-01-01T00:01:00Z",
        }),
      ),
    );
  });

  it("changes when a different goal is set", () => {
    expect(goalReconciliationKey(makeGoal({ objective: "a" }))).not.toBe(
      goalReconciliationKey(makeGoal({ objective: "b" })),
    );
  });

  it("distinguishes a cleared goal from an active one", () => {
    expect(goalReconciliationKey(null)).not.toBe(
      goalReconciliationKey(makeGoal()),
    );
  });
});
