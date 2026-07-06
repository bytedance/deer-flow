import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import { collectRenderedSubtasks } from "@/core/tasks/subtask-render";

function subagentGroup(messages: Message[]) {
  return {
    id: "group-1",
    type: "assistant:subagent",
    messages,
  } as const;
}

describe("collectRenderedSubtasks", () => {
  it("derives an in-progress task while the subagent turn is still streaming", () => {
    const groups = [
      subagentGroup([
        {
          type: "ai",
          tool_calls: [
            {
              id: "task-1",
              name: "task",
              args: {
                subagent_type: "researcher",
                description: "Research the topic",
                prompt: "Find sources",
              },
            },
          ],
          content: "",
        } as unknown as Message,
      ]),
    ];

    const rendered = collectRenderedSubtasks(groups, () => true, "failed");

    expect(rendered.tasks.get("task-1")).toMatchObject({
      id: "task-1",
      status: "in_progress",
      subagent_type: "researcher",
    });
    expect(rendered.updates).toHaveLength(1);
  });

  it("marks a task as failed once its turn ended without a tool result", () => {
    const groups = [
      subagentGroup([
        {
          type: "ai",
          tool_calls: [
            {
              id: "task-1",
              name: "task",
              args: {
                subagent_type: "researcher",
                description: "Research the topic",
                prompt: "Find sources",
              },
            },
          ],
          content: "",
        } as unknown as Message,
      ]),
    ];

    const rendered = collectRenderedSubtasks(
      groups,
      () => false,
      "Subtask failed",
    );

    expect(rendered.tasks.get("task-1")).toMatchObject({
      id: "task-1",
      status: "failed",
      error: "Subtask failed",
    });
  });

  it("merges a tool result into the fallback task snapshot", () => {
    const groups = [
      subagentGroup([
        {
          type: "ai",
          tool_calls: [
            {
              id: "task-1",
              name: "task",
              args: {
                subagent_type: "researcher",
                description: "Research the topic",
                prompt: "Find sources",
              },
            },
          ],
          content: "",
        } as unknown as Message,
        {
          type: "tool",
          tool_call_id: "task-1",
          content: "ignored by structured status",
          additional_kwargs: {
            subagent_status: "completed",
            subagent_result_brief: "done",
          },
        } as unknown as Message,
      ]),
    ];

    const rendered = collectRenderedSubtasks(groups, () => false, "failed");

    expect(rendered.tasks.get("task-1")).toMatchObject({
      id: "task-1",
      status: "completed",
      result: "done",
    });
    expect(rendered.updates).toHaveLength(2);
  });
});
