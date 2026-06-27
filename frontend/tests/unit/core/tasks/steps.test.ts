import type { AIMessage } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import { mergeSubtaskStep } from "@/core/tasks/steps";

function aiMessage(id: string): AIMessage {
  return {
    id,
    type: "ai",
    content: "",
    tool_calls: [
      {
        id: `tool-${id}`,
        name: "web_search",
        args: { query: id },
        type: "tool_call",
      },
    ],
  } as AIMessage;
}

describe("mergeSubtaskStep", () => {
  it("orders running messages by backend message_index", () => {
    const third = aiMessage("third");
    const first = aiMessage("first");

    const steps = mergeSubtaskStep(
      mergeSubtaskStep(undefined, third, 3),
      first,
      1,
    );

    expect(steps.map((step) => step.message.id)).toEqual(["first", "third"]);
  });

  it("replaces an existing indexed step instead of duplicating it", () => {
    const initial = aiMessage("initial");
    const replacement = aiMessage("replacement");

    const steps = mergeSubtaskStep(
      mergeSubtaskStep(undefined, initial, 2),
      replacement,
      2,
    );

    expect(steps).toHaveLength(1);
    expect(steps[0]?.message.id).toBe("replacement");
  });

  it("deduplicates unindexed messages by message id", () => {
    const initial = aiMessage("same");
    const replacement = aiMessage("same");

    const steps = mergeSubtaskStep(
      mergeSubtaskStep(undefined, initial),
      replacement,
    );

    expect(steps).toHaveLength(1);
    expect(steps[0]?.message).toBe(replacement);
  });

  it("replaces an unindexed duplicate when a later indexed copy arrives", () => {
    const initial = aiMessage("same");
    const replacement = aiMessage("same");

    const steps = mergeSubtaskStep(
      mergeSubtaskStep(undefined, initial),
      replacement,
      1,
    );

    expect(steps).toHaveLength(1);
    expect(steps[0]?.message).toBe(replacement);
    expect(steps[0]?.messageIndex).toBe(1);
  });

  it("appends unindexed messages without ids", () => {
    const first = { ...aiMessage("first"), id: undefined } as AIMessage;
    const second = { ...aiMessage("second"), id: undefined } as AIMessage;

    const steps = mergeSubtaskStep(mergeSubtaskStep(undefined, first), second);

    expect(steps).toHaveLength(2);
  });
});
