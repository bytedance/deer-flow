import type { AgentModelSettings, AgentSubagentPolicy } from "@/core/agents";
import type { Model } from "@/core/models/types";

export const MAX_AGENT_OUTPUT_TOKENS = 200_000;
export const MAX_AGENT_SUBAGENT_CONCURRENCY = 64;
export const MAX_AGENT_SUBAGENTS_PER_RUN = 50;

// Sentinel select values. The empty string is not usable because Radix Select
// reserves it for the placeholder, so both "inherit" escape hatches use a
// distinct token that can never collide with a real model / effort value.
export const DEFAULT_MODEL_VALUE = "__default__";
export const INHERIT_VALUE = "__inherit__";

export type ThinkingSelection = "__inherit__" | "on" | "off";
export type SubagentAccessSelection = "all" | "none" | "selected";

export function allowedSubagentsToSelection(
  value: string[] | null | undefined,
): SubagentAccessSelection {
  if (value == null) return "all";
  return value.length === 0 ? "none" : "selected";
}

export function selectionToAllowedSubagents(
  selection: SubagentAccessSelection,
  selectedNames: string[],
): string[] | null {
  if (selection === "all") return null;
  if (selection === "none") return [];
  return selectedNames;
}

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

type AgentSubagentPolicyValidationError = "max_concurrent" | "max_total";

type ParsedAgentSubagentPolicy =
  | { ok: true; policy: Required<AgentSubagentPolicy> }
  | { ok: false; error: AgentSubagentPolicyValidationError };

function parseSubagentLimit(
  input: string,
  maximum: number,
): number | null | undefined {
  if (input.trim() === "") return null;
  const value = Number(input);
  return Number.isInteger(value) && value >= 1 && value <= maximum
    ? value
    : undefined;
}

export function parseAgentSubagentPolicyDraft({
  maxConcurrent,
  maxTotal,
  maxConcurrentBadInput = false,
  maxTotalBadInput = false,
}: {
  maxConcurrent: string;
  maxTotal: string;
  maxConcurrentBadInput?: boolean;
  maxTotalBadInput?: boolean;
}): ParsedAgentSubagentPolicy {
  if (maxConcurrentBadInput) return { ok: false, error: "max_concurrent" };
  if (maxTotalBadInput) return { ok: false, error: "max_total" };
  const concurrent = parseSubagentLimit(
    maxConcurrent,
    MAX_AGENT_SUBAGENT_CONCURRENCY,
  );
  if (concurrent === undefined) return { ok: false, error: "max_concurrent" };
  const total = parseSubagentLimit(maxTotal, MAX_AGENT_SUBAGENTS_PER_RUN);
  if (total === undefined) return { ok: false, error: "max_total" };

  return { ok: true, policy: { max_concurrent: concurrent, max_total: total } };
}
