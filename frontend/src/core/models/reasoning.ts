import type { Model, ModelReasoningCapabilities } from "./types";

/** The vocabulary DeerFlow's mode presets and legacy profiles use. */
export const GENERIC_REASONING_EFFORTS = [
  "minimal",
  "low",
  "medium",
  "high",
] as const;

export type GenericReasoningEffort = (typeof GENERIC_REASONING_EFFORTS)[number];

/**
 * An effort value sent to the Gateway. Provider contracts may add values
 * outside the generic set (for example `max` or `xhigh`), so this stays open
 * while keeping autocomplete for the generic ones.
 */
export type ReasoningEffortValue = GenericReasoningEffort | (string & {});

export type InputMode = "flash" | "thinking" | "pro" | "ultra";

const MODE_EFFORT_PRESETS: Record<InputMode, GenericReasoningEffort> = {
  flash: "minimal",
  thinking: "low",
  pro: "medium",
  ultra: "high",
};

const UNSUPPORTED: ModelReasoningCapabilities = {
  thinking: "unsupported",
  effort: null,
  history: null,
  source: "legacy",
};

/**
 * Normalize a model's reasoning capabilities. Prefers the contract projected
 * by the Gateway and falls back to the legacy booleans for older backends, so
 * every caller reads one shape.
 */
export function getReasoningCapabilities(
  model: Model | null | undefined,
): ModelReasoningCapabilities {
  if (!model) {
    return UNSUPPORTED;
  }
  if (model.reasoning) {
    return model.reasoning;
  }
  return {
    thinking: model.supports_thinking ? "optional" : "unsupported",
    effort: model.supports_reasoning_effort
      ? { values: [...GENERIC_REASONING_EFFORTS], default: null, aliases: {} }
      : null,
    history: null,
    source: "legacy",
  };
}

export function supportsThinking(model: Model | null | undefined): boolean {
  return getReasoningCapabilities(model).thinking !== "unsupported";
}

export function isThinkingRequired(model: Model | null | undefined): boolean {
  return getReasoningCapabilities(model).thinking === "required";
}

/** Effort values the UI may offer for this model, in display order. */
export function getReasoningEffortOptions(
  model: Model | null | undefined,
): string[] {
  return getReasoningCapabilities(model).effort?.values ?? [];
}

/**
 * Map a requested effort onto a value the model accepts.
 *
 * - `undefined` stays `undefined` (the Gateway applies the contract default).
 * - Legacy profiles keep only their advertised generic values. A remembered
 *   contract-only value is dropped when the user switches models.
 * - Declared contracts keep accepted values, map generic values through the
 *   contract's aliases, and otherwise fall back to the contract default.
 */
export function resolveReasoningEffort(
  model: Model | null | undefined,
  requested: ReasoningEffortValue | undefined,
): ReasoningEffortValue | undefined {
  if (requested === undefined) {
    return undefined;
  }
  const capabilities = getReasoningCapabilities(model);
  if (capabilities.source === "legacy") {
    return capabilities.effort?.values.includes(requested)
      ? requested
      : undefined;
  }
  const effort = capabilities.effort;
  if (!effort) {
    return undefined;
  }
  if (effort.values.includes(requested)) {
    return requested;
  }
  const alias = effort.aliases[requested];
  if (alias !== undefined) {
    return alias;
  }
  return effort.default ?? undefined;
}

/**
 * Clamp a chat mode to what the model supports: no thinking mode on a model
 * without thinking, and never `flash` on a model whose thinking is required.
 */
export function getResolvedMode(
  mode: InputMode | undefined,
  model: Model | null | undefined,
): InputMode {
  const { thinking } = getReasoningCapabilities(model);
  if (thinking === "unsupported") {
    return "flash";
  }
  if (thinking === "required") {
    if (mode === "flash") {
      return "thinking";
    }
    return mode ?? "pro";
  }
  return mode ?? "pro";
}

/** The effort a mode preset implies, mapped onto the model's contract. */
export function reasoningEffortForMode(
  mode: InputMode,
  model: Model | null | undefined,
): ReasoningEffortValue | undefined {
  return resolveReasoningEffort(model, MODE_EFFORT_PRESETS[mode]);
}
