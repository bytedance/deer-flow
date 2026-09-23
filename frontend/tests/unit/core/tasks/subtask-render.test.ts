import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import type { MessageGroup } from "@/core/messages/utils";
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
    const groups: MessageGroup[] = [
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
      (groupIndex) => threadIsLoading && groupIndex === groups.length - 1,
      "failed",
      "Subtask",
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
      "Subtask",
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

    const rendered = collectRenderedSubtasks(
      groups,
      () => false,
      "failed",
      "Subtask",
    );

    expect(rendered.tasks.get("task-1")).toMatchObject({
      id: "task-1",
      status: "completed",
      result: "done",
    });
    expect(rendered.updates).toHaveLength(2);
  });
});

describe("collectRenderedSubtasks description fallback", () => {
  it.each([
    [undefined, "Use the prompt", "Use the prompt"],
    ["   ", "  Trimmed prompt  ", "Trimmed prompt"],
    [undefined, "", "Localized subtask"],
  ])(
    "preserves the current-main description fallback for %s / %s",
    (description, prompt, expected) => {
      const rendered = collectRenderedSubtasks(
        [
          subagentGroup([
            {
              type: "ai",
              content: "",
              tool_calls: [
                {
                  id: "task-1",
                  name: "task",
                  args: { description, prompt, subagent_type: "researcher" },
                },
              ],
            } as Message,
          ]),
        ],
        () => true,
        "failed",
        "Localized subtask",
      );
      expect(rendered.tasks.get("task-1")?.description).toBe(expected);
    },
  );
});

describe("resolveRenderedSubtask", () => {
  it("keeps live arguments when a partial snapshot omits them", () => {
    const live = baseTask();
    const fallback = { id: "task-1", status: "in_progress" } as Subtask;
    expect(resolveRenderedSubtask(live, fallback)).toEqual(live);
  });

  it.each(["completed", "failed"] as const)(
    "preserves %s lifecycle and runtime data while refreshing message arguments",
    (status) => {
      const live = baseTask({
        status,
        result: "done",
        error: "failed",
        stopReason: "token_capped",
        modelName: "test-model",
        usage: { inputTokens: 8, outputTokens: 2, totalTokens: 10 },
        steps: [{ kind: "tool", message_index: 1, text: "done" }],
        latestMessage: { id: "live", type: "ai", content: "working" },
      });
      const resolved = resolveRenderedSubtask(
        live,
        baseTask({
          description: "Current title",
          prompt: "Current prompt",
          subagent_type: "general-purpose",
        }),
      );
      expect(resolved).toEqual({
        ...live,
        description: "Current title",
        prompt: "Current prompt",
        subagent_type: "general-purpose",
      });
    },
  );

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

  it("uses current message arguments while preserving live runtime state", () => {
    const resolved = resolveRenderedSubtask(
      baseTask({
        status: "in_progress",
        description: "live",
        modelName: "test-model",
        prompt: "old prompt",
      }),
      baseTask({ status: "in_progress", description: "fallback", prompt: "" }),
    );

    expect(resolved).toMatchObject({
      status: "in_progress",
      description: "fallback",
      prompt: "",
      modelName: "test-model",
    });
  });

  it("fills a metadata-only live task from an in-progress fallback", () => {
    const resolved = resolveRenderedSubtask(
      {
        id: "task-1",
        modelName: "claude-3-7-sonnet",
      } as Subtask,
      baseTask({ status: "in_progress", description: "fallback" }),
    );

    expect(resolved).toMatchObject({
      id: "task-1",
      status: "in_progress",
      description: "fallback",
      modelName: "claude-3-7-sonnet",
    });
  });

  it("preserves fields available only on a live task after completion", () => {
    const resolved = resolveRenderedSubtask(
      {
        ...baseTask({ status: "in_progress" }),
        futureLiveMetadata: "preserved",
      } as Subtask & { futureLiveMetadata: string },
      baseTask({ status: "completed", result: "done" }),
    ) as Subtask & { futureLiveMetadata?: string };

    expect(resolved).toMatchObject({
      status: "completed",
      result: "done",
      futureLiveMetadata: "preserved",
    });
  });
});
