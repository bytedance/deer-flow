import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  collectRenderedSubtasks,
  resolveRenderedSubtask,
} from "@/core/tasks/subtask-render";
import type { Subtask } from "@/core/tasks/types";

function baseTask(overrides: Partial<Subtask> = {}): Subtask {
  return {
    id: "task-1",
    status: "in_progress",
    subagent_type: "researcher",
    description: "Research the topic",
    prompt: "Find sources",
    ...overrides,
  };
}

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
      {
        id: "group-0",
        type: "human",
        messages: [],
      },
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

    const threadIsLoading = true;
    const rendered = collectRenderedSubtasks(
      groups,
      (_messages, groupIndex) =>
        threadIsLoading && groupIndex === groups.length - 1,
      "failed",
    );

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

describe("resolveRenderedSubtask", () => {
  it("uses an in-progress fallback before the live task is available", () => {
    const fallbackTask = baseTask({
      status: "in_progress",
      description: "fallback",
    });

    expect(resolveRenderedSubtask(undefined, fallbackTask)).toBe(fallbackTask);
  });

  it("prefers a terminal fallback snapshot over a stale live task", () => {
    const resolved = resolveRenderedSubtask(
      baseTask({
        status: "in_progress",
        modelName: "claude-3-7-sonnet",
        usage: {
          inputTokens: 800,
          outputTokens: 200,
          totalTokens: 1_000,
        },
        latestMessage: { id: "live-1" } as Subtask["latestMessage"],
      }),
      baseTask({
        status: "failed",
        error: "Subtask failed",
      }),
    );

    expect(resolved).toMatchObject({
      status: "failed",
      error: "Subtask failed",
      modelName: "claude-3-7-sonnet",
      usage: {
        inputTokens: 800,
        outputTokens: 200,
        totalTokens: 1_000,
      },
      latestMessage: { id: "live-1" },
    });
  });

  it("keeps the live task when the fallback snapshot is still in progress", () => {
    const resolved = resolveRenderedSubtask(
      baseTask({ status: "in_progress", description: "live" }),
      baseTask({ status: "in_progress", description: "fallback" }),
    );

    expect(resolved).toMatchObject({
      status: "in_progress",
      description: "live",
    });
  });
});
