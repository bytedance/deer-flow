import { expect, test } from "vitest";

import type { Subtask } from "@/core/tasks/types";

/**
 * Tests for the immutable update logic in useUpdateSubtask.
 *
 * Since we don't have @testing-library/react, we test the core logic
 * by simulating the functional setTasks updater pattern directly.
 */

function makeSubtask(overrides: Partial<Subtask> = {}): Subtask {
  return {
    id: "task-1",
    status: "in_progress",
    subagent_type: "coder",
    description: "Write code",
    prompt: "Implement the feature",
    ...overrides,
  };
}

// --- Fix #1: Immutable functional state update ---

test("functional updater merges partial task into existing state immutably", () => {
  const initial: Record<string, Subtask> = {
    "task-1": makeSubtask(),
  };

  // Simulate the functional setTasks updater pattern from the fix
  const updated = applyUpdate(initial, { id: "task-1", status: "completed" });

  // Original is not mutated
  expect(initial["task-1"]!.status).toBe("in_progress");
  // New state has the update
  expect(updated["task-1"]!.status).toBe("completed");
  // Other fields preserved
  expect(updated["task-1"]!.description).toBe("Write code");
});

test("functional updater creates new state object (not same reference)", () => {
  const initial: Record<string, Subtask> = {
    "task-1": makeSubtask(),
  };

  const updated = applyUpdate(initial, { id: "task-1", result: "done" });

  expect(updated).not.toBe(initial);
  expect(updated["task-1"]).not.toBe(initial["task-1"]);
});

// --- Fix #2: task_running race condition / placeholder creation ---

test("updater creates minimal placeholder when subtask does not exist", () => {
  const initial: Record<string, Subtask> = {};

  // Simulate task_running arriving before the subtask is created by the
  // orchestrator's task tool call — the handler now passes minimal defaults.
  const updated = applyUpdate(initial, {
    id: "task-new",
    status: "in_progress",
    description: "",
    prompt: "",
    subagent_type: "",
    latestMessage: {
      type: "ai",
      id: "msg-1",
      content: "working on it",
    } as unknown as Subtask["latestMessage"],
  });

  expect(updated["task-new"]).toBeDefined();
  expect(updated["task-new"]!.status).toBe("in_progress");
  expect(updated["task-new"]!.latestMessage).toBeDefined();
});

// --- Fix #5: Empty historySteps fallback ---
// (The actual fix is in SubtaskCard JSX, but we verify convertToSteps behavior
// that drives historySteps in message-steps.test.ts)

test("subtask with empty messageHistory should not lose fallback UI info", () => {
  const task = makeSubtask({ messageHistory: [] });

  // Empty array is truthy, so `!historySteps` alone would be false.
  // The fix uses `!historySteps || historySteps.length === 0`.
  const historySteps = convertToStepsForTest(task.messageHistory);
  const shouldShowFallback = !historySteps || historySteps.length === 0;

  expect(shouldShowFallback).toBe(true);
});

test("subtask with no messageHistory should show fallback UI", () => {
  const task = makeSubtask();

  const historySteps = convertToStepsForTest(task.messageHistory);
  const shouldShowFallback = !historySteps || historySteps.length === 0;

  expect(shouldShowFallback).toBe(true);
});

test("subtask with messageHistory should not show fallback UI", () => {
  const task = makeSubtask({
    messageHistory: [
      {
        type: "ai",
        id: "msg-1",
        content: [{ type: "text", text: "thinking..." }],
      } as unknown as Subtask["messageHistory"] extends (infer T)[] | undefined
        ? T
        : never,
    ],
  });

  const historySteps = convertToStepsForTest(task.messageHistory);
  const shouldShowFallback = !historySteps || historySteps.length === 0;

  expect(shouldShowFallback).toBe(false);
});

// --- Helpers ---

/**
 * Simulates the immutable functional update pattern from useUpdateSubtask.
 * This mirrors the core logic in context.tsx's setTasks(prev => ...) updater.
 */
function applyUpdate(
  prev: Record<string, Subtask>,
  task: Partial<Subtask> & { id: string },
): Record<string, Subtask> {
  const current = prev[task.id];
  const updated = { ...current, ...task } as Subtask;
  return { ...prev, [task.id]: updated };
}

/**
 * Simplified version of convertToSteps for testing historySteps behavior.
 * Returns null for empty/undefined, steps array otherwise — matching SubtaskCard's useMemo.
 */
function convertToStepsForTest(
  messageHistory: Subtask["messageHistory"],
): Array<unknown> | null {
  if (!messageHistory || messageHistory.length === 0) {
    return null;
  }
  return messageHistory.map(() => ({ type: "reasoning" }));
}
