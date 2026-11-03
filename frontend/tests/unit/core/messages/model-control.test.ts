import type { Message } from "@langchain/langgraph-sdk";
import { expect, it } from "@rstest/core";

import { modelControlDisplayText } from "@/core/messages/model-control";
import { modelTaskInput } from "@/core/models/control";

it("separates an already applied control from the business task without losing its visible text", () => {
  const original = "Use B for this turn: calculate 17 * 23";
  const input = modelTaskInput(original, {
    status: "resolved",
    scope: "turn",
    query: "B",
    model_name: "B",
    candidates: [],
    task_offset: original.indexOf("calculate"),
  });
  expect(input.text).toBe("calculate 17 * 23");
  const message = {
    type: "human",
    content: input.text,
    additional_kwargs: input.additionalKwargs,
  } as Message;
  expect(modelControlDisplayText(message)).toBe(original);
  expect(
    modelControlDisplayText({ ...message, content: "an edited task" }),
  ).toBeNull();
  expect(
    modelControlDisplayText({ ...message, type: "ai" } as Message),
  ).toBeNull();
});

it("preserves long Unicode task bodies beyond the preview window", () => {
  const original = "Use B for this turn: " + "🦌".repeat(5000);
  const input = modelTaskInput(original, {
    status: "resolved",
    scope: "turn",
    query: "B",
    model_name: "B",
    candidates: [],
    task_offset: 21,
  });
  expect(input.text).toBe("🦌".repeat(5000));
});

it("leaves the delegation request for the parent agent to dispatch", () => {
  const text = "Ask B to calculate 17 * 23";
  expect(
    modelTaskInput(text, {
      status: "resolved",
      scope: "task",
      query: "B",
      model_name: "B",
      candidates: [],
      task_offset: 9,
    }).text,
  ).toBe(text);
});
