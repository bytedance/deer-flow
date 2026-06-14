import { expect, test } from "vitest";

import {
  getCollapsedThinkingSummary,
  summarizeCollapsedThinkingStep,
} from "@/core/messages/thinking";

test("summarizeCollapsedThinkingStep returns empty summary for missing reasoning", () => {
  expect(summarizeCollapsedThinkingStep()).toBe("");
  expect(summarizeCollapsedThinkingStep("   ")).toBe("");
});

test("summarizeCollapsedThinkingStep strips markdown before previewing collapsed reasoning", () => {
  expect(
    summarizeCollapsedThinkingStep(
      [
        "## Plan",
        "> inspect `thread_id` handling",
        "![trace](trace.png)",
        "[open file](https://example.com)",
        "```ts",
        "const hidden = true;",
        "```",
      ].join("\n"),
    ),
  ).toBe("Plan inspect thread id handling open file");
});

test("summarizeCollapsedThinkingStep truncates long collapsed reasoning previews", () => {
  const summary = summarizeCollapsedThinkingStep(`${"a".repeat(181)} trailing`);

  expect(summary).toHaveLength(183);
  expect(summary).toBe(`${"a".repeat(180)}...`);
});

test("getCollapsedThinkingSummary hides summary when preview setting is disabled", () => {
  expect(
    getCollapsedThinkingSummary({
      reasoning: "inspect latest tool result",
      showCollapsedThinkingStep: false,
      showLastThinking: false,
    }),
  ).toBe("");
});

test("getCollapsedThinkingSummary shows summary only when setting is enabled and thinking is collapsed", () => {
  expect(
    getCollapsedThinkingSummary({
      reasoning: "inspect latest tool result",
      showCollapsedThinkingStep: true,
      showLastThinking: false,
    }),
  ).toBe("inspect latest tool result");
});

test("getCollapsedThinkingSummary hides summary while thinking is expanded", () => {
  expect(
    getCollapsedThinkingSummary({
      reasoning: "inspect latest tool result",
      showCollapsedThinkingStep: true,
      showLastThinking: true,
    }),
  ).toBe("");
});
