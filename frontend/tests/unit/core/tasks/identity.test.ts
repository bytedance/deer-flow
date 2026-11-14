import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import { matchesExecution, subtaskKey } from "@/core/tasks/identity";
import { taskEventToSubtaskUpdate } from "@/core/tasks/lifecycle";
import { eventsToSteps } from "@/core/tasks/steps";
import {
  collectRenderedSubtasks,
  findSubtaskResultMessage,
} from "@/core/tasks/subtask-render";
import { computeNextSubtask } from "@/core/tasks/subtask-update";
import type { Subtask } from "@/core/tasks/types";

describe("delegated task identity", () => {
  it("keeps a dispatch key before and after learning execution identity", () => {
    const key = subtaskKey("call", "dispatch");
    const started = taskEventToSubtaskUpdate({
      type: "task_started",
      task_id: "call",
      dispatch_id: "dispatch",
      execution_id: "execution",
      executor: "acp",
    });
    expect(started?.id).toBe(key);
    expect(started?.executionId).toBe("execution");
    expect(subtaskKey("call", "other")).not.toBe(key);
    expect(subtaskKey("legacy")).toBe("legacy");
  });

  it("keeps repeated provider IDs separate in final messages and history", () => {
    const call = (id: string): Message => ({
      type: "ai",
      id,
      content: "",
      tool_calls: [
        {
          id: "same",
          name: "task",
          args: { prompt: id, subagent_type: "external" },
        },
      ],
    });
    const result = (dispatch: string, execution: string): Message => ({
      type: "tool",
      name: "task",
      tool_call_id: "same",
      content: execution,
      additional_kwargs: {
        subagent_status: "completed",
        subagent_result_brief: execution,
        subagent_dispatch_id: dispatch,
        subagent_execution_id: execution,
        subagent_executor: "acp",
      },
    });
    const first = result("one", "exec-one"),
      second = result("two", "exec-two");
    const group = {
      id: "group",
      type: "assistant:subagent" as const,
      messages: [call("one"), first, call("two"), second],
    };
    const rendered = collectRenderedSubtasks(
      [group],
      () => false,
      "Failed",
      "Task",
    );
    expect(rendered.tasks.get(subtaskKey("same", "one"))?.executionId).toBe(
      "exec-one",
    );
    expect(rendered.tasks.get(subtaskKey("same", "two"))?.executionId).toBe(
      "exec-two",
    );
    expect(findSubtaskResultMessage(group, "same", "two")).toBe(second);
    const missingFirst = collectRenderedSubtasks(
      [{ ...group, messages: [call("one"), call("two"), second] }],
      () => false,
      "Failed",
      "Task",
    );
    expect(missingFirst.tasks.get(subtaskKey("same", "one"))?.status).toBe(
      "failed",
    );
    const events = ["exec-one", "exec-two"].map((execution_id) => ({
      event_type: "subagent.step",
      content: {
        task_id: "same",
        execution_id,
        message_index: 1,
        kind: "ai",
        text: execution_id,
      },
    }));
    expect(
      eventsToSteps(events, "same", { executionId: "exec-two" }).map(
        (step) => step.text,
      ),
    ).toEqual(["exec-two"]);
    expect(matchesExecution({ executionId: "exec-two" }, {})).toBe(false);
  });

  it("rejects progress from another execution and retains a terminal status", () => {
    const previous: Subtask = {
      id: "key",
      executionId: "one",
      status: "completed",
      prompt: "Work",
      description: "Work",
      subagent_type: "external",
    };
    expect(
      computeNextSubtask(previous, {
        id: "key",
        executionId: "two",
        status: "in_progress",
      }).changed,
    ).toBe(false);
    expect(
      computeNextSubtask(previous, {
        id: "key",
        executionId: "one",
        status: "in_progress",
      }).next.status,
    ).toBe("completed");
  });
});
