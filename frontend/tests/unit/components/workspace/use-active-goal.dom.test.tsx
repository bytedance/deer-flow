import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";
import { act, renderHook } from "@testing-library/react";

import { useActiveGoal } from "@/components/workspace/use-active-goal";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

const GOAL: GoalState = {
  objective: "Write a three-line summary of README.md",
  status: "active",
  created_at: "2026-10-07T00:00:00Z",
  updated_at: "2026-10-07T00:00:00Z",
  continuation_count: 0,
  max_continuations: 8,
  no_progress_count: 0,
  max_no_progress_continuations: 2,
};

const HUMAN = { id: "h-1", type: "human", content: GOAL.objective } as Message;
const AI = { id: "ai-1", type: "ai", content: "Done: summary." } as Message;

function recordOf(
  goal: GoalState,
  overrides: Partial<ThreadGoalOutcome> = {},
): ThreadGoalOutcome {
  return {
    status: "achieved",
    objective: goal.objective,
    goal_created_at: goal.created_at,
    achieved_at: "2026-10-07T00:01:00Z",
    continuation_count: 0,
    max_continuations: 8,
    reason: "The summary has three lines.",
    relied_on_assumption: false,
    reply_message_id: "ai-1",
    ...overrides,
  };
}

type Props = {
  threadId: string;
  goal?: unknown;
  outcome?: unknown;
  messages: Message[];
};

function renderGoal(initial: Partial<Props> = {}) {
  return renderHook(
    ({ threadId, goal, outcome, messages }: Props) =>
      useActiveGoal(threadId, goal, outcome, messages),
    {
      initialProps: {
        threadId: "thread-1",
        messages: [HUMAN],
        ...initial,
      } as Props,
    },
  );
}

describe("useActiveGoal", () => {
  it("drops the set override once the server records that goal as met", () => {
    const { result, rerender } = renderGoal();
    act(() => result.current.setLocalGoal(GOAL, "set"));
    expect(result.current.hasGoal).toBe(true);

    // The satisfied clear: values without the goal key, plus the record.
    rerender({
      threadId: "thread-1",
      outcome: recordOf(GOAL),
      messages: [HUMAN, AI],
    });

    expect(result.current.hasGoal).toBe(false);
    expect(result.current.activeGoal).toBeNull();
    expect(result.current.goalOutcome).toEqual(recordOf(GOAL));
  });

  it("keeps an override whose goal is not the recorded one", () => {
    const { result, rerender } = renderGoal();
    const again = { ...GOAL, created_at: "2026-10-07T00:02:00Z" };
    act(() => result.current.setLocalGoal(again, "set"));
    rerender({
      threadId: "thread-1",
      outcome: recordOf(GOAL),
      messages: [HUMAN, AI],
    });
    expect(result.current.activeGoal).toBe(again);
    expect(result.current.goalOutcome).toBeNull();
  });

  it("keeps a goal set in the same tick the earlier goal's record arrives", () => {
    const { result, rerender } = renderGoal();
    act(() => result.current.setLocalGoal(GOAL, "set"));
    const next = {
      ...GOAL,
      objective: "Translate it",
      created_at: "2026-10-07T00:03:00Z",
    };
    act(() => {
      result.current.setLocalGoal(next, "set");
      rerender({
        threadId: "thread-1",
        outcome: recordOf(GOAL),
        messages: [HUMAN, AI],
      });
    });
    expect(result.current.activeGoal).toBe(next);
  });

  it("hides the record after this tab's clear, but not after a status read", () => {
    const shown = { outcome: recordOf(GOAL), messages: [HUMAN, AI] };
    const status = renderGoal(shown);
    expect(status.result.current.goalOutcome).not.toBeNull();
    // GET /goal answers goal: null while only the record exists.
    act(() => status.result.current.setLocalGoal(null, "status"));
    expect(status.result.current.goalOutcome).toEqual(recordOf(GOAL));

    const clear = renderGoal(shown);
    act(() => clear.result.current.setLocalGoal(null, "clear"));
    expect(clear.result.current.goalOutcome).toBeNull();
    expect(clear.result.current.hasGoal).toBe(false);
  });

  it("shows a newer record again after hiding an older one", () => {
    const { result, rerender } = renderGoal({
      outcome: recordOf(GOAL),
      messages: [HUMAN, AI],
    });
    act(() => result.current.setLocalGoal(GOAL, "set"));
    expect(result.current.goalOutcome).toBeNull();

    const newer = recordOf(GOAL, { achieved_at: "2026-10-07T00:09:00Z" });
    rerender({ threadId: "thread-1", outcome: newer, messages: [HUMAN, AI] });
    expect(result.current.hasGoal).toBe(false);
    expect(result.current.goalOutcome).toEqual(newer);
  });

  it("resets the override and the hidden record on a thread switch", () => {
    const shown = { outcome: recordOf(GOAL), messages: [HUMAN, AI] };
    const { result, rerender } = renderGoal(shown);
    act(() => result.current.setLocalGoal(null, "clear"));
    expect(result.current.goalOutcome).toBeNull();

    rerender({ threadId: "thread-2", ...shown });
    expect(result.current.goalOutcome).toEqual(recordOf(GOAL));

    act(() => result.current.setLocalGoal(GOAL, "set"));
    rerender({ threadId: "thread-3", messages: [] });
    expect(result.current.activeGoal).toBeNull();
  });

  it("lets an active server goal hide a coexisting record", () => {
    const { result } = renderGoal({
      goal: { ...GOAL, objective: "Next" },
      outcome: recordOf(GOAL),
      messages: [HUMAN, AI],
    });
    expect(result.current.activeGoal?.objective).toBe("Next");
    expect(result.current.goalOutcome).toBeNull();
  });

  it("drops a status-read goal without created_at once its '' record arrives", () => {
    // POST /state stored the goal without created_at, so thread values leave
    // it out, but the status read shows it and the backend still locks edit.
    const bare = { objective: GOAL.objective, status: "active" } as GoalState;
    const { result, rerender } = renderGoal({ goal: bare });
    expect(result.current.hasGoal).toBe(false);
    act(() => result.current.setLocalGoal(bare, "status"));
    expect(result.current.activeGoal).toBe(bare);

    // The satisfied clear: no goal key, plus the record.
    rerender({
      threadId: "thread-1",
      outcome: recordOf(GOAL, { goal_created_at: "" }),
      messages: [HUMAN, AI],
    });
    expect(result.current.hasGoal).toBe(false);
    expect(result.current.goalOutcome).toEqual(
      recordOf(GOAL, { goal_created_at: "" }),
    );
  });

  it("does not treat a malformed goal value as a set goal", () => {
    const { result } = renderGoal({ goal: { objective: "finish" } });
    expect(result.current.hasGoal).toBe(false);
    expect(result.current.activeGoal).toBeNull();
  });
});
