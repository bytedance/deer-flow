import { describe, expect, it } from "vitest";

import { mergeSubtaskUpdate } from "@/core/tasks/context";
import type { Subtask } from "@/core/tasks/types";

describe("mergeSubtaskUpdate", () => {
  it("updates a subtask without mutating the current tasks object", () => {
    const originalTask: Subtask = {
      id: "task-1",
      status: "in_progress",
      subagent_type: "researcher",
      description: "Research the topic",
      prompt: "Find sources",
    };
    const tasks = { "task-1": originalTask };

    const next = mergeSubtaskUpdate(tasks, {
      id: "task-1",
      status: "completed",
      result: "done",
    });

    expect(next).not.toBe(tasks);
    expect(next["task-1"]).not.toBe(originalTask);
    expect(next["task-1"]).toMatchObject({
      id: "task-1",
      status: "completed",
      result: "done",
    });
    expect(tasks["task-1"]).toBe(originalTask);
    expect(tasks["task-1"].status).toBe("in_progress");
  });

  it("returns the same tasks object when an update does not change a subtask", () => {
    const originalTask: Subtask = {
      id: "task-1",
      status: "in_progress",
      subagent_type: "researcher",
      description: "Research the topic",
      prompt: "Find sources",
    };
    const tasks = { "task-1": originalTask };

    const next = mergeSubtaskUpdate(tasks, {
      id: "task-1",
      status: "in_progress",
    });

    expect(next).toBe(tasks);
    expect(next["task-1"]).toBe(originalTask);
  });
});
