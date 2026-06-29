import { useEffect, useState } from "react";

import type { GoalState } from "@/core/threads/types";

import { goalReconciliationKey } from "./goal-status-helpers";

export type UseActiveGoalResult = {
  /** The goal to render — the optimistic override while set, else server state. */
  activeGoal: GoalState | null;
  hasGoal: boolean;
  /** Apply an optimistic goal after a `/goal` command (or `null` to hide it). */
  setLocalGoal: (goal: GoalState | null) => void;
};

/**
 * Reconciles the optimistic `/goal`-command result with the server's goal state.
 *
 * A `/goal` command updates the UI immediately via `setLocalGoal`, but that
 * override is dropped as soon as the server goal changes — switching threads, or
 * the stream delivering a new `continuation_count` / a cleared goal — so the
 * agent's live continuation counter is always reflected instead of the frozen
 * optimistic copy. Shared by the workspace and agent chat pages.
 */
export function useActiveGoal(
  threadId: string,
  serverGoal: GoalState | null,
): UseActiveGoalResult {
  const [localGoal, setLocalGoal] = useState<GoalState | null | undefined>(
    undefined,
  );
  const serverGoalKey = goalReconciliationKey(serverGoal);

  useEffect(() => {
    setLocalGoal(undefined);
  }, [threadId, serverGoalKey]);

  const activeGoal = localGoal !== undefined ? localGoal : serverGoal;
  return { activeGoal, hasGoal: Boolean(activeGoal), setLocalGoal };
}
