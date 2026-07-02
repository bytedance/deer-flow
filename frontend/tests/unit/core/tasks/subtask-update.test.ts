import { describe, expect, it } from "@rstest/core";

import type { SubtaskStep } from "@/core/tasks/steps";
import {
  computeNextSubtask,
  isTerminalSubtaskStatus,
} from "@/core/tasks/subtask-update";
import type { Subtask } from "@/core/tasks/types";

function baseTask(overrides: Partial<Subtask> = {}): Subtask {
  return {
    id: "t1",
    status: "in_progress",
    subagent_type: "general-purpose",
    description: "research",
    prompt: "do it",
    ...overrides,
  };
}

function step(message_index: number): SubtaskStep {
  return {
    kind: "tool",
    message_index,
    text: `step ${message_index}`,
    truncated: false,
  };
}

describe("computeNextSubtask", () => {
  it("merges step deltas into the provided previous, preserving both", () => {
    const previous = baseTask({ steps: [step(1), step(2)] });

    const { next } = computeNextSubtask(previous, {
      id: "t1",
      steps: [step(3)],
    });

    // Regression for #3779 stale-closure race: next is derived from whatever
    // `previous` is passed (the functional-update latest state), so concurrently
    // arrived steps are kept, not clobbered by a backfill resolving late.
    expect(next.steps?.map((s) => s.message_index)).toEqual([1, 2, 3]);
  });

  it("does not drop steps present only on the latest previous", () => {
    // Simulates a backfill that fired when previous had 0 steps, but by the time
    // it resolves the latest previous already has SSE steps 1..2. The backfill
    // brings historical steps 1..3; the merge must retain all, not reset to [].
    const latestPrevious = baseTask({ steps: [step(1), step(2)] });

    const { next } = computeNextSubtask(latestPrevious, {
      id: "t1",
      steps: [step(1), step(2), step(3)],
    });

    expect(next.steps?.map((s) => s.message_index)).toEqual([1, 2, 3]);
  });

  it("keeps a terminal status stable against a late in_progress write", () => {
    const previous = baseTask({ status: "completed" });

    const { next, becameTerminal } = computeNextSubtask(previous, {
      id: "t1",
      status: "in_progress",
    });

    expect(next.status).toBe("completed");
    expect(becameTerminal).toBe(false);
  });

  it("flags becameTerminal on the first transition to a terminal status", () => {
    const previous = baseTask({ status: "in_progress" });

    const { next, becameTerminal } = computeNextSubtask(previous, {
      id: "t1",
      status: "completed",
      result: "done",
    });

    expect(next.status).toBe("completed");
    expect(next.result).toBe("done");
    expect(becameTerminal).toBe(true);
  });

  it("handles an undefined previous (first write for a task)", () => {
    const { next, becameTerminal } = computeNextSubtask(undefined, {
      id: "t1",
      status: "in_progress",
      subagent_type: "bash",
      description: "run",
      prompt: "p",
      steps: [step(1)],
    });

    expect(next.id).toBe("t1");
    expect(next.steps?.map((s) => s.message_index)).toEqual([1]);
    expect(becameTerminal).toBe(false);
  });
});

describe("isTerminalSubtaskStatus", () => {
  it("recognizes terminal statuses only", () => {
    expect(isTerminalSubtaskStatus("completed")).toBe(true);
    expect(isTerminalSubtaskStatus("failed")).toBe(true);
    expect(isTerminalSubtaskStatus("in_progress")).toBe(false);
    expect(isTerminalSubtaskStatus(undefined)).toBe(false);
  });
});
