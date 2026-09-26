import { describe, expect, it } from "@rstest/core";

import {
  resolveActiveGoal,
  shouldResetLocalGoalOverride,
} from "@/components/workspace/use-active-goal";
import type { GoalState } from "@/core/threads/types";

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

  it("resets an optimistic goal when the server explicitly clears the goal", () => {
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
