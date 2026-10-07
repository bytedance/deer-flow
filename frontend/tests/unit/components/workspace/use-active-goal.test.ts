import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import { goalOutcomeKey } from "@/components/workspace/goal-status-helpers";
import {
  normalizeGoalStatusRead,
  normalizeServerGoal,
  resolveActiveGoal,
  resolveGoalView,
  shouldResetLocalGoalOverride,
} from "@/components/workspace/use-active-goal";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

function makeGoal(overrides: Partial<GoalState> = {}): GoalState {
  return {
    objective: "ship the landing page",
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

describe("resolveActiveGoal", () => {
  it("keeps the optimistic goal when stream values omit the goal field", () => {
    const localGoal = makeGoal();

    expect(resolveActiveGoal(localGoal, undefined)).toBe(localGoal);
  });

  it("falls back to null when neither local nor server state has a goal", () => {
    expect(resolveActiveGoal(undefined, undefined)).toBeNull();
  });
});

describe("shouldResetLocalGoalOverride", () => {
  it("does not reset an optimistic goal when the same thread omits goal from stream values", () => {
    expect(
      shouldResetLocalGoalOverride({
        serverGoalProvided: false,
        threadChanged: false,
      }),
    ).toBe(false);
  });

  it("resets an optimistic goal when the server reports a goal value", () => {
    expect(
      shouldResetLocalGoalOverride({
        serverGoalProvided: true,
        threadChanged: false,
      }),
    ).toBe(true);
  });

  it("resets an optimistic goal on real thread navigation", () => {
    expect(
      shouldResetLocalGoalOverride({
        serverGoalProvided: false,
        threadChanged: true,
      }),
    ).toBe(true);
  });
});

describe("normalizeServerGoal", () => {
  it("keeps a missing key missing and drops a malformed or inactive goal", () => {
    const goal = makeGoal();
    expect(normalizeServerGoal(undefined)).toBeUndefined();
    expect(normalizeServerGoal(goal)).toBe(goal);
    expect(normalizeServerGoal(null)).toBeNull();
    // POST /state can store a dict that is not an active goal.
    expect(normalizeServerGoal({ objective: "finish" })).toBeNull();
    expect(normalizeServerGoal({ ...goal, status: "paused" })).toBeNull();
  });
});

describe("normalizeGoalStatusRead", () => {
  it("keeps what the backend treats as an active goal, and nothing else", () => {
    const goal = makeGoal();
    expect(normalizeGoalStatusRead(goal)).toBe(goal);
    // Stored without created_at: still active on the server, so edit is 409.
    const bare = { objective: "finish", status: "active" };
    expect(normalizeGoalStatusRead(bare)).toBe(bare);
    // No status: the server allows the edit, so this is no goal.
    expect(normalizeGoalStatusRead({ objective: "finish" })).toBeNull();
    expect(normalizeGoalStatusRead({ ...goal, status: "paused" })).toBeNull();
    expect(normalizeGoalStatusRead({ status: "active" })).toBeNull();
    expect(normalizeGoalStatusRead(undefined)).toBeNull();
    expect(normalizeGoalStatusRead(null)).toBeNull();
    expect(normalizeGoalStatusRead([goal])).toBeNull();
    expect(normalizeGoalStatusRead("finish")).toBeNull();
  });
});

describe("resolveGoalView", () => {
  const anchor = { id: "ai-1", type: "ai", content: "Done." } as Message;
  const outcome: ThreadGoalOutcome = {
    status: "achieved",
    objective: "ship the landing page",
    goal_created_at: "2026-01-01T00:00:00Z",
    achieved_at: "2026-01-01T00:05:00Z",
    continuation_count: 0,
    max_continuations: 8,
    reason: "Shipped.",
    relied_on_assumption: false,
    reply_message_id: "ai-1",
  };
  const view = (overrides: Partial<Parameters<typeof resolveGoalView>[0]>) =>
    resolveGoalView({
      localGoal: undefined,
      serverGoal: undefined,
      serverOutcome: outcome,
      hiddenOutcomeKey: null,
      messages: [anchor],
      ...overrides,
    });

  it("shows a current record when no goal is active", () => {
    expect(view({})).toEqual({ activeGoal: null, goalOutcome: outcome });
  });

  it("lets an active goal, local or server, hide the record", () => {
    const goal = makeGoal({ objective: "next" });
    expect(view({ localGoal: goal })).toEqual({
      activeGoal: goal,
      goalOutcome: null,
    });
    expect(view({ serverGoal: goal }).goalOutcome).toBeNull();
  });

  it("hides the record this tab removed and one the chat moved past", () => {
    expect(
      view({ hiddenOutcomeKey: goalOutcomeKey(outcome) }).goalOutcome,
    ).toBeNull();
    expect(
      view({
        messages: [
          anchor,
          { id: "h-2", type: "human", content: "more" } as Message,
        ],
      }).goalOutcome,
    ).toBeNull();
  });

  it("ignores a record of an unknown status", () => {
    expect(
      view({ serverOutcome: { ...outcome, status: "cleared" } }).goalOutcome,
    ).toBeNull();
  });
});
