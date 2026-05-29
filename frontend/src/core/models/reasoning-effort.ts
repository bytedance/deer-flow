import type { ReasoningEffort } from "../threads";

import type { Model } from "./types";

export type ReasoningMode = "flash" | "thinking" | "pro" | "ultra";

export const DEFAULT_REASONING_EFFORTS: ReasoningEffort[] = [
  "minimal",
  "low",
  "medium",
  "high",
];

const DEFAULT_REASONING_EFFORT_BY_MODE: Record<
  ReasoningMode,
  ReasoningEffort | undefined
> = {
  flash: undefined,
  thinking: "low",
  pro: "medium",
  ultra: "high",
};

export function getModelReasoningEfforts(
  model?: Pick<Model, "reasoning_efforts" | "supports_reasoning_effort">,
): ReasoningEffort[] {
  if (!model?.supports_reasoning_effort) {
    return [];
  }
  if (model.reasoning_efforts?.length) {
    return model.reasoning_efforts;
  }
  return DEFAULT_REASONING_EFFORTS;
}

export function getDefaultReasoningEffort(
  mode: ReasoningMode,
  allowedEfforts: readonly ReasoningEffort[],
): ReasoningEffort | undefined {
  if (mode === "flash" || allowedEfforts.length === 0) {
    return undefined;
  }

  const preferred = DEFAULT_REASONING_EFFORT_BY_MODE[mode];
  if (preferred && allowedEfforts.includes(preferred)) {
    return preferred;
  }

  return allowedEfforts[0];
}

export function normalizeReasoningEffort(
  effort: ReasoningEffort | undefined,
  mode: ReasoningMode,
  allowedEfforts: readonly ReasoningEffort[],
): ReasoningEffort | undefined {
  if (mode === "flash") {
    return undefined;
  }
  if (effort && allowedEfforts.includes(effort)) {
    return effort;
  }
  return getDefaultReasoningEffort(mode, allowedEfforts);
}
