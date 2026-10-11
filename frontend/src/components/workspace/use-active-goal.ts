import type { Message } from "@langchain/langgraph-sdk";
import { useCallback, useEffect, useRef, useState } from "react";

import { isGoalState } from "@/core/threads/stream-state";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

import {
  goalOutcomeKey,
  goalReconciliationKey,
  isGoalOutcomeCurrent,
  isThreadGoalOutcome,
  sameGoalInstance,
} from "./goal-status-helpers";

/** What a `/goal` command did: set and clear write the goal, status only reads it. */
export type GoalChangeKind = "set" | "clear" | "status";

export type UseActiveGoalResult = {
  /** The goal to render — the optimistic override while set, else server state. */
  activeGoal: GoalState | null;
  hasGoal: boolean;
  /** The current "Goal met" record; null while a goal is active. */
  goalOutcome: ThreadGoalOutcome | null;
  /** Apply the result of a `/goal` command (`null` hides the goal). */
  setLocalGoal: (goal: GoalState | null, kind: GoalChangeKind) => void;
};

export function resolveActiveGoal(
  localGoal: GoalState | null | undefined,
  serverGoal: GoalState | null | undefined,
): GoalState | null {
  return localGoal !== undefined ? localGoal : (serverGoal ?? null);
}

/**
 * The goal and met record to render. An active goal wins over any record; a
 * record shows only while it is current (`isGoalOutcomeCurrent`) and this
 * tab's own `/goal` set or clear has not removed it on the server.
 */
export function resolveGoalView({
  localGoal,
  serverGoal,
  serverOutcome,
  hiddenOutcomeKey,
  messages,
}: {
  localGoal: GoalState | null | undefined;
  serverGoal: GoalState | null | undefined;
  serverOutcome: unknown;
  hiddenOutcomeKey: string | null;
  messages: readonly Message[];
}): { activeGoal: GoalState | null; goalOutcome: ThreadGoalOutcome | null } {
  const activeGoal = resolveActiveGoal(localGoal, serverGoal);
  const goalOutcome =
    !activeGoal &&
    isThreadGoalOutcome(serverOutcome) &&
    goalOutcomeKey(serverOutcome) !== hiddenOutcomeKey &&
    isGoalOutcomeCurrent(serverOutcome, messages)
      ? serverOutcome
      : null;
  return { activeGoal, goalOutcome };
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

/** A present `goal` value that is not an active goal counts as no goal. */
export function normalizeServerGoal(
  value: unknown,
): GoalState | null | undefined {
  return value === undefined ? undefined : isGoalState(value) ? value : null;
}

/**
 * A `/goal` status read, judged by the same rule as thread values. A goal
 * stored without `created_at` stays; its met record has `goal_created_at` "".
 */
export function normalizeGoalStatusRead(value: unknown): GoalState | null {
  return isGoalState(value) ? value : null;
}

/**
 * Reconciles the optimistic `/goal`-command result with the server's goal
 * state and its met record.
 *
 * A `/goal` command updates the UI immediately via `setLocalGoal`. The
 * override yields when the server reports goal state: a thread switch, a
 * present `goal` value (a new `continuation_count`, a stand-down), or a met
 * record of that same goal. Chat streams carry no `values` snapshots, so a
 * goal met on the first run arrives only as a frame without the `goal` key
 * plus `goal_outcome`. A missing key alone is not a clear, since partial
 * values can omit it; the record is. Matching the record to the override's
 * own goal keeps a goal set in the same tick.
 */
export function useActiveGoal(
  threadId: string,
  serverGoalValue: unknown,
  serverOutcome: unknown,
  messages: readonly Message[],
): UseActiveGoalResult {
  const [localGoal, setLocalGoalState] = useState<GoalState | null | undefined>(
    undefined,
  );
  const [hiddenOutcomeKey, setHiddenOutcomeKey] = useState<string | null>(null);
  const previousThreadIdRef = useRef(threadId);
  const serverGoal = normalizeServerGoal(serverGoalValue);
  const serverGoalProvided = serverGoal !== undefined;
  const serverGoalKey = serverGoalProvided
    ? goalReconciliationKey(serverGoal)
    : "missing";
  const outcome = isThreadGoalOutcome(serverOutcome) ? serverOutcome : null;
  const outcomeKey = goalOutcomeKey(outcome);
  const outcomeRef = useRef(outcome);
  outcomeRef.current = outcome;

  useEffect(() => {
    const threadChanged = previousThreadIdRef.current !== threadId;
    previousThreadIdRef.current = threadId;
    if (threadChanged) {
      setHiddenOutcomeKey(null);
    }
    if (shouldResetLocalGoalOverride({ serverGoalProvided, threadChanged })) {
      setLocalGoalState(undefined);
    }
  }, [serverGoalKey, serverGoalProvided, threadId]);

  useEffect(() => {
    const met = outcomeRef.current;
    if (!met) {
      return;
    }
    setLocalGoalState((previous) =>
      previous && sameGoalInstance(previous, met) ? undefined : previous,
    );
  }, [outcomeKey]);

  const setLocalGoal = useCallback(
    (goal: GoalState | null, kind: GoalChangeKind) => {
      setLocalGoalState(goal);
      if (kind !== "status") {
        // The write removed the record on the server, but this tab's values
        // keep it until the next run.
        setHiddenOutcomeKey(goalOutcomeKey(outcomeRef.current));
      }
    },
    [],
  );

  const { activeGoal, goalOutcome } = resolveGoalView({
    localGoal,
    serverGoal,
    serverOutcome: outcome,
    hiddenOutcomeKey,
    messages,
  });
  return {
    activeGoal,
    hasGoal: Boolean(activeGoal),
    goalOutcome,
    setLocalGoal,
  };
}
