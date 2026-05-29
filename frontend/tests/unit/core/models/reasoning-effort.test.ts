import { expect, test } from "vitest";

import {
  getDefaultReasoningEffort,
  getModelReasoningEfforts,
  normalizeReasoningEffort,
} from "@/core/models/reasoning-effort";
import type { Model } from "@/core/models/types";

function model(overrides: Partial<Model>): Model {
  return {
    id: "deepseek",
    name: "deepseek",
    model: "deepseek-v4-pro",
    display_name: "DeepSeek",
    ...overrides,
  };
}

test("uses provider-specific reasoning effort values when configured", () => {
  const efforts = getModelReasoningEfforts(
    model({
      supports_reasoning_effort: true,
      reasoning_efforts: ["low", "medium", "high", "max", "xhigh"],
    }),
  );

  expect(efforts).toEqual(["low", "medium", "high", "max", "xhigh"]);
  expect(efforts).not.toContain("minimal");
});

test("falls back to built-in reasoning efforts for legacy model configs", () => {
  expect(
    getModelReasoningEfforts(model({ supports_reasoning_effort: true })),
  ).toEqual(["minimal", "low", "medium", "high"]);
});

test("normalizes stale local reasoning effort to the mode default", () => {
  const efforts = ["low", "medium", "high", "max", "xhigh"] as const;

  expect(normalizeReasoningEffort("minimal", "pro", efforts)).toBe("medium");
  expect(normalizeReasoningEffort("minimal", "ultra", efforts)).toBe("high");
});

test("does not send reasoning effort in flash mode", () => {
  const efforts = ["minimal", "low", "medium", "high"] as const;

  expect(getDefaultReasoningEffort("flash", efforts)).toBeUndefined();
  expect(normalizeReasoningEffort("minimal", "flash", efforts)).toBeUndefined();
});
