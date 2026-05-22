import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import { buildSubtaskMapFromMessages } from "@/core/tasks/derive";

function aiWithTaskCall(id: string, args: Record<string, unknown>): AIMessage {
  return {
    id,
    type: "ai",
    content: "",
    tool_calls: [
      {
        id,
        name: "task",
        args,
      },
    ],
  } as unknown as AIMessage;
}

function toolReturn(toolCallId: string, content: string): Message {
  return {
    id: `t-${toolCallId}`,
    type: "tool",
    content,
    name: "task",
    tool_call_id: toolCallId,
  } as unknown as Message;
}

describe("buildSubtaskMapFromMessages", () => {
  it("returns empty map when there are no subagent task calls", () => {
    expect(buildSubtaskMapFromMessages([])).toEqual({});
  });

  it("seeds a card as in_progress as soon as the AI emits the task call", () => {
    const map = buildSubtaskMapFromMessages([
      aiWithTaskCall("task-1", {
        subagent_type: "general-purpose",
        description: "Run echo command",
        prompt: "echo hi",
      }),
    ]);
    expect(map["task-1"]!).toEqual({
      id: "task-1",
      subagent_type: "general-purpose",
      description: "Run echo command",
      prompt: "echo hi",
      status: "in_progress",
    });
  });

  it("flips to completed when the matching tool message arrives", () => {
    const map = buildSubtaskMapFromMessages([
      aiWithTaskCall("task-1", {
        subagent_type: "general-purpose",
        description: "Run echo command",
        prompt: "echo hi",
      }),
      toolReturn("task-1", "Task Succeeded. Result: payload"),
    ]);
    expect(map["task-1"]!.status).toBe("completed");
    expect(map["task-1"]!.result).toBe("payload");
  });

  it("flips to failed when the task tool returns an Error: wrapper", () => {
    const map = buildSubtaskMapFromMessages([
      aiWithTaskCall("task-2", {
        subagent_type: "general-purpose",
        description: "Run thing",
        prompt: "do thing",
      }),
      toolReturn(
        "task-2",
        "Error: Tool 'task' failed with TypeError: oops. Continue with available context, or choose an alternative tool.",
      ),
    ]);
    expect(map["task-2"]!.status).toBe("failed");
    expect(map["task-2"]!.error).toContain("TypeError");
  });

  it("keeps in_progress when there is no matching tool message yet", () => {
    const map = buildSubtaskMapFromMessages([
      aiWithTaskCall("task-3", {
        subagent_type: "general-purpose",
        description: "x",
        prompt: "y",
      }),
    ]);
    expect(map["task-3"]!.status).toBe("in_progress");
  });

  it("handles multiple subagent task calls in the same AI message", () => {
    const msg = {
      id: "ai-multi",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "call-a",
          name: "task",
          args: {
            subagent_type: "general-purpose",
            description: "alpha",
            prompt: "p1",
          },
        },
        {
          id: "call-b",
          name: "task",
          args: {
            subagent_type: "general-purpose",
            description: "beta",
            prompt: "p2",
          },
        },
      ],
    } as unknown as AIMessage;

    const map = buildSubtaskMapFromMessages([
      msg,
      toolReturn("call-a", "Task Succeeded. Result: A"),
    ]);
    expect(Object.keys(map).sort()).toEqual(["call-a", "call-b"]);
    expect(map["call-a"]!.status).toBe("completed");
    expect(map["call-b"]!.status).toBe("in_progress");
  });

  it("ignores non-task tool calls", () => {
    const msg = {
      id: "ai-shell",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "call-shell",
          name: "bash",
          args: { command: "ls" },
        },
      ],
    } as unknown as AIMessage;

    const map = buildSubtaskMapFromMessages([
      msg,
      toolReturn("call-shell", "ok"),
    ]);
    expect(map).toEqual({});
  });

  // The structured `additional_kwargs.subagent_status` path is owned by
  // #3146 / PR #3154. This derive function is forward-compatible: as soon
  // as `parseSubtaskResult` grows the second parameter, the structured
  // path will win here automatically. The end-to-end coverage of that
  // wiring lives in `subtask-result.test.ts` once #3146 ships.
});
