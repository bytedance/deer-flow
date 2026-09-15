import type { GoalState } from "@/core/threads";

export type GoalContinuationDisplay = {
  count: number;
  max: number;
};

/**
 * Decide the continuation counter to render for an active goal.
 *
 * Returns `null` until the agent has actually auto-continued at least once
 * (`continuation_count > 0`). Before that, the raw "0/8" reads as a mysterious
 * score, so the counter is hidden; once continuation starts it surfaces as
 * "{count}/{max}" with an explanatory tooltip.
 */
export function getGoalContinuationDisplay(
  goal: Pick<GoalState, "continuation_count" | "max_continuations">,
): GoalContinuationDisplay | null {
  const count = goal.continuation_count ?? 0;
  const max = goal.max_continuations ?? 0;
  if (!Number.isFinite(count) || count <= 0) {
    return null;
  }
  return { count, max };
}

/**
 * Stable signature of the *server* goal, used to decide when an optimistic
 * client override should yield back to server state.
 *
 * It changes whenever a new goal is set (`created_at`), the agent auto-continues
 * (`continuation_count`/`updated_at`), or the backend clears/satisfies the goal
 * (`null`). `useActiveGoal` resets its optimistic copy when this key changes, so
 * the streamed continuation counter is never permanently shadowed.
 */
export function goalReconciliationKey(goal: GoalState | null): string {
  if (!goal) {
    return "none";
  }
  return [
    goal.objective,
    goal.status,
    goal.created_at ?? "",
    goal.updated_at ?? "",
    goal.continuation_count ?? 0,
  ].join("|");
}
