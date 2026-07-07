import { describe, expect, it } from "@rstest/core";

import {
  getGoalContinuationDisplay,
  goalReconciliationKey,
} from "@/components/workspace/goal-status-helpers";
import type { GoalState } from "@/core/threads/types";

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

describe("getGoalContinuationDisplay", () => {
  it("hides the counter before the agent has auto-continued", () => {
    expect(
      getGoalContinuationDisplay({
        continuation_count: 0,
        max_continuations: 8,
      }),
    ).toBeNull();
  });

  it("shows count and max once continuation has started", () => {
    expect(
      getGoalContinuationDisplay({
        continuation_count: 1,
        max_continuations: 8,
      }),
    ).toEqual({ count: 1, max: 8 });
    expect(
      getGoalContinuationDisplay({
        continuation_count: 8,
        max_continuations: 8,
      }),
    ).toEqual({ count: 8, max: 8 });
  });

  it("treats missing or negative counts as hidden", () => {
    expect(
      getGoalContinuationDisplay({
        continuation_count: -1,
        max_continuations: 8,
      }),
    ).toBeNull();
    expect(
      getGoalContinuationDisplay({
        continuation_count: undefined as unknown as number,
        max_continuations: undefined as unknown as number,
      }),
    ).toBeNull();
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
