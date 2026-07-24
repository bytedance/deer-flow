import type { AgentModelSettings } from "@/core/agents";
import type { Model } from "@/core/models/types";

export const MAX_AGENT_OUTPUT_TOKENS = 200_000;

// Sentinel select values. The empty string is not usable because Radix Select
// reserves it for the placeholder, so both "inherit" escape hatches use a
// distinct token that can never collide with a real model / effort value.
export const DEFAULT_MODEL_VALUE = "__default__";
export const INHERIT_VALUE = "__inherit__";

export type ThinkingSelection = "__inherit__" | "on" | "off";

/**
 * Map a persisted ``thinking_enabled`` (``true`` / ``false`` / ``null``) to the
 * tri-state select value. ``null``/undefined means "inherit the runtime default"
 * — which is thinking *on* today (see ``_resolve_runtime_option`` in
 * ``lead_agent/agent.py``), so seeding a plain on/off switch to ``false`` would
 * silently disable thinking on an untouched save. The explicit "Inherit" state
 * keeps an unchanged save a no-op and lets the user return to inherit.
 */
export function thinkingEnabledToSelection(
  value: boolean | null | undefined,
): ThinkingSelection {
  if (value == null) return INHERIT_VALUE;
  return value ? "on" : "off";
}

/** Inverse of {@link thinkingEnabledToSelection} for the update payload. */
export function selectionToThinkingEnabled(
  selection: ThinkingSelection,
): boolean | null {
  if (selection === "on") return true;
  if (selection === "off") return false;
  return null;
}

/**
 * Resolve the model whose capabilities gate the thinking / reasoning controls.
 * When the agent inherits the global default (``__default__``), fall back to the
 * effective default model (``models[0]``, matching ``_resolve_model_name`` on
 * the backend) so those controls are not silently hidden for an agent that has
 * not pinned an explicit model.
 */
export function resolveEffectiveModel(
  models: Model[],
  modelValue: string,
): Model | undefined {
  if (modelValue === DEFAULT_MODEL_VALUE) return models[0];
  return models.find((m) => m.name === modelValue);
}

export type AgentSettingsValidationError = "temperature" | "max_tokens";

export type ParsedAgentModelSettings =
  | {
      ok: true;
      modelSettings: AgentModelSettings | null;
    }
  | {
      ok: false;
      error: AgentSettingsValidationError;
    };

export function parseAgentModelSettingsDraft({
  temperature,
  maxTokens,
}: {
  temperature: string;
  maxTokens: string;
}): ParsedAgentModelSettings {
  const trimmedTemp = temperature.trim();
  const trimmedMax = maxTokens.trim();

  let temperatureValue: number | null = null;
  if (trimmedTemp !== "") {
    temperatureValue = Number(trimmedTemp);
    if (
      Number.isNaN(temperatureValue) ||
      temperatureValue < 0 ||
      temperatureValue > 2
    ) {
      return { ok: false, error: "temperature" };
    }
  }

  let maxTokensValue: number | null = null;
  if (trimmedMax !== "") {
    maxTokensValue = Number(trimmedMax);
    if (
      !Number.isInteger(maxTokensValue) ||
      maxTokensValue < 1 ||
      maxTokensValue > MAX_AGENT_OUTPUT_TOKENS
    ) {
      return { ok: false, error: "max_tokens" };
    }
  }

  const hasSettings = temperatureValue != null || maxTokensValue != null;
  return {
    ok: true,
    modelSettings: hasSettings
      ? { temperature: temperatureValue, max_tokens: maxTokensValue }
      : null,
  };
}
