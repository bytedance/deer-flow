import { useEffect, useRef, useState } from "react";

import type { GoalState } from "@/core/threads/types";

import { goalReconciliationKey } from "./goal-status-helpers";

export type UseActiveGoalResult = {
  /** The goal to render — the optimistic override while set, else server state. */
  activeGoal: GoalState | null;
  hasGoal: boolean;
  /** Apply an optimistic goal after a `/goal` command (or `null` to hide it). */
  setLocalGoal: (goal: GoalState | null) => void;
};

export function resolveActiveGoal(
  localGoal: GoalState | null | undefined,
  serverGoal: GoalState | null | undefined,
): GoalState | null {
  return localGoal !== undefined ? localGoal : (serverGoal ?? null);
}

export function shouldResetLocalGoalOverride({
  serverGoalProvided,
  threadChanged,
}: {
  serverGoalProvided: boolean;
  threadChanged: boolean;
}): boolean {
  if (threadChanged) {
    return true;
  }
  return serverGoalProvided;
}

/**
 * Reconciles the optimistic `/goal`-command result with the server's goal state.
 *
 * A `/goal` command updates the UI immediately via `setLocalGoal`, but that
 * override is dropped as soon as the server explicitly reports goal state —
 * switching threads, a new `continuation_count`, or a cleared goal. A stream
 * chunk that omits the `goal` field is not treated as a clear, because
 * clarification interrupts can publish partial values while the active goal is
 * still present in the checkpoint.
 */
export function useActiveGoal(
  threadId: string,
  serverGoal: GoalState | null | undefined,
): UseActiveGoalResult {
  const [localGoal, setLocalGoal] = useState<GoalState | null | undefined>(
    undefined,
  );
  const previousThreadIdRef = useRef(threadId);
  const serverGoalProvided = serverGoal !== undefined;
  const serverGoalKey = serverGoalProvided
    ? goalReconciliationKey(serverGoal)
    : "missing";

  useEffect(() => {
    const threadChanged = previousThreadIdRef.current !== threadId;
    previousThreadIdRef.current = threadId;
    if (shouldResetLocalGoalOverride({ serverGoalProvided, threadChanged })) {
      setLocalGoal(undefined);
    }
  }, [serverGoalKey, serverGoalProvided, threadId]);

  const activeGoal = resolveActiveGoal(localGoal, serverGoal);
  return { activeGoal, hasGoal: Boolean(activeGoal), setLocalGoal };
}
