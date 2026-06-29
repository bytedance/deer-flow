import { describe, expect, it } from "@rstest/core";

import { getGoalContinuationDisplay } from "@/components/workspace/goal-status-helpers";

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
