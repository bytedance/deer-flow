import { describe, expect, it } from "@rstest/core";

import {
  eventsToSteps,
  mergeSteps,
  messageToStep,
  toolStepsForDisplay,
} from "@/core/tasks/steps";

describe("messageToStep", () => {
  it("normalizes an AI message into an ai step with tool calls", () => {
    const step = messageToStep(
      {
        type: "ai",
        id: "ai-1",
        content: "Let me search.",
        tool_calls: [{ name: "web_search", args: { query: "x" }, id: "c1" }],
      },
      1,
    );

    expect(step.kind).toBe("ai");
    expect(step.message_index).toBe(1);
    expect(step.text).toBe("Let me search.");
    expect(step.tool_calls).toEqual([{ name: "web_search", args: { query: "x" } }]);
    expect(step.tool_name).toBeUndefined();
  });

  it("normalizes a tool message into a tool step with its output", () => {
    const step = messageToStep(
      { type: "tool", id: "t-1", name: "web_search", content: "results" },
      2,
    );

    expect(step.kind).toBe("tool");
    expect(step.tool_name).toBe("web_search");
    expect(step.text).toBe("results");
    expect(step.tool_calls).toBeUndefined();
  });

  it("flattens list-of-blocks content to text", () => {
    const step = messageToStep(
      {
        type: "ai",
        content: [
          { type: "text", text: "first" },
          { type: "text", text: "second" },
        ],
      },
      1,
    );

    expect(step.text).toContain("first");
    expect(step.text).toContain("second");
  });
});

describe("mergeSteps", () => {
  it("appends a new step", () => {
    const a = messageToStep({ type: "ai", content: "a" }, 1);
    const b = messageToStep({ type: "tool", name: "x", content: "b" }, 2);

    expect(mergeSteps([a], [b])).toEqual([a, b]);
  });

  it("dedupes by message_index, preferring the incoming step", () => {
    const old = messageToStep({ type: "ai", content: "old" }, 1);
    const fresh = messageToStep({ type: "ai", content: "fresh" }, 1);

    const merged = mergeSteps([old], [fresh]);

    expect(merged).toHaveLength(1);
    expect(merged[0]!.text).toBe("fresh");
  });

  it("keeps steps ordered by message_index", () => {
    const s1 = messageToStep({ type: "ai", content: "1" }, 1);
    const s2 = messageToStep({ type: "ai", content: "2" }, 2);
    const s3 = messageToStep({ type: "ai", content: "3" }, 3);

    const merged = mergeSteps([s3], [s1, s2]);

    expect(merged.map((s) => s.message_index)).toEqual([1, 2, 3]);
  });
});

describe("toolStepsForDisplay", () => {
  it("keeps only tool steps (the tools that ran), in order", () => {
    const steps = [
      messageToStep(
        { type: "ai", content: "searching", tool_calls: [{ name: "web_search", args: {} }] },
        1,
      ),
      messageToStep({ type: "tool", name: "web_search", content: "big result body" }, 2),
      messageToStep({ type: "ai", content: "final answer" }, 3),
      messageToStep({ type: "tool", name: "read_file", content: "file contents" }, 4),
    ];

    const display = toolStepsForDisplay(steps);

    expect(display.map((s) => s.tool_name)).toEqual(["web_search", "read_file"]);
  });

  it("returns empty for undefined or no tool steps", () => {
    expect(toolStepsForDisplay(undefined)).toEqual([]);
    expect(
      toolStepsForDisplay([messageToStep({ type: "ai", content: "thinking" }, 1)]),
    ).toEqual([]);
  });
});

describe("eventsToSteps", () => {
  const events = [
    {
      event_type: "subagent.start",
      content: { task_id: "call_1", description: "research" },
      metadata: { task_id: "call_1" },
    },
    {
      event_type: "subagent.step",
      content: { task_id: "call_1", message_index: 2, kind: "tool", tool_name: "web_search", text: "results", truncated: false },
      metadata: { task_id: "call_1", message_index: 2 },
    },
    {
      event_type: "subagent.step",
      content: { task_id: "call_1", message_index: 1, kind: "ai", text: "searching", tool_calls: [{ name: "web_search", args: {} }] },
      metadata: { task_id: "call_1", message_index: 1 },
    },
    {
      event_type: "subagent.step",
      content: { task_id: "other", message_index: 1, kind: "ai", text: "nope" },
      metadata: { task_id: "other", message_index: 1 },
    },
    {
      event_type: "subagent.end",
      content: { task_id: "call_1", status: "completed", result: "done" },
      metadata: { task_id: "call_1" },
    },
  ];

  it("maps subagent.step events for the task into ordered steps", () => {
    const steps = eventsToSteps(events, "call_1");

    expect(steps.map((s) => s.message_index)).toEqual([1, 2]);
    expect(steps[0]!.kind).toBe("ai");
    expect(steps[1]!.kind).toBe("tool");
    expect(steps[1]!.tool_name).toBe("web_search");
  });

  it("ignores steps belonging to other tasks and non-step events", () => {
    const steps = eventsToSteps(events, "call_1");

    expect(steps.every((s) => s.text !== "nope")).toBe(true);
    expect(steps).toHaveLength(2);
  });

  it("returns empty array when no events match", () => {
    expect(eventsToSteps(events, "missing")).toEqual([]);
    expect(eventsToSteps([], "call_1")).toEqual([]);
  });
});
