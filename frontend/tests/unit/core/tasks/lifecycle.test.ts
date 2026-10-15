import { describe, expect, it } from "@rstest/core";

import { taskEventToSubtaskUpdate } from "@/core/tasks/lifecycle";

describe("taskEventToSubtaskUpdate", () => {
  it("maps a task-start event to the effective model for that task", () => {
    expect(
      taskEventToSubtaskUpdate({
        type: "task_started",
        task_id: "call-1",
        description: "Research auth",
        model_name: "claude-3-7-sonnet",
      }),
    ).toEqual({
      id: "call-1",
      modelName: "claude-3-7-sonnet",
    });
  });

  it("maps a running event to its cumulative token snapshot", () => {
    expect(
      taskEventToSubtaskUpdate({
        type: "task_running",
        task_id: "call-1",
        model_name: "claude-3-7-sonnet",
        usage: {
          input_tokens: 100,
          output_tokens: 20,
          total_tokens: 120,
        },
      }),
    ).toEqual({
      id: "call-1",
      modelName: "claude-3-7-sonnet",
      usage: {
        inputTokens: 100,
        outputTokens: 20,
        totalTokens: 120,
      },
    });
  });
});
