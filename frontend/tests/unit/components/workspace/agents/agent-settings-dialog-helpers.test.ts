import { describe, expect, it } from "@rstest/core";

import {
  allowedSubagentsToSelection,
  DEFAULT_MODEL_VALUE,
  INHERIT_VALUE,
  MAX_AGENT_OUTPUT_TOKENS,
  MAX_AGENT_SUBAGENT_CONCURRENCY,
  MAX_AGENT_SUBAGENTS_PER_RUN,
  parseAgentModelSettingsDraft,
  parseAgentSubagentPolicyDraft,
  resolveEffectiveModel,
  selectionToAllowedSubagents,
  selectionToThinkingEnabled,
  thinkingEnabledToSelection,
} from "@/components/workspace/agents/agent-settings-dialog-helpers";
import type { Model } from "@/core/models/types";

describe("parseAgentModelSettingsDraft", () => {
  it("rejects invalid temperature values before save", () => {
    expect(
      parseAgentModelSettingsDraft({ temperature: "-0.1", maxTokens: "" }),
    ).toEqual({ ok: false, error: "temperature" });
    expect(
      parseAgentModelSettingsDraft({ temperature: "2.1", maxTokens: "" }),
    ).toEqual({ ok: false, error: "temperature" });
    expect(
      parseAgentModelSettingsDraft({ temperature: "warm", maxTokens: "" }),
    ).toEqual({ ok: false, error: "temperature" });
  });

  it("rejects invalid max token values before save", () => {
    expect(
      parseAgentModelSettingsDraft({ temperature: "", maxTokens: "0" }),
    ).toEqual({ ok: false, error: "max_tokens" });
    expect(
      parseAgentModelSettingsDraft({ temperature: "", maxTokens: "1.5" }),
    ).toEqual({ ok: false, error: "max_tokens" });
    expect(
      parseAgentModelSettingsDraft({
        temperature: "",
        maxTokens: String(MAX_AGENT_OUTPUT_TOKENS + 1),
      }),
    ).toEqual({ ok: false, error: "max_tokens" });
  });

  it("returns null settings when both fields inherit", () => {
    expect(
      parseAgentModelSettingsDraft({ temperature: " ", maxTokens: "" }),
    ).toEqual({ ok: true, modelSettings: null });
  });

  it("keeps explicit nulls for cleared sub-fields when another setting remains", () => {
    expect(
      parseAgentModelSettingsDraft({ temperature: "0.2", maxTokens: "" }),
    ).toEqual({
      ok: true,
      modelSettings: { temperature: 0.2, max_tokens: null },
    });
  });
});

describe("parseAgentSubagentPolicyDraft", () => {
  it("accepts independently unset bounded limits", () => {
    expect(
      parseAgentSubagentPolicyDraft({ maxConcurrent: "4", maxTotal: "" }),
    ).toEqual({
      ok: true,
      policy: { max_concurrent: 4, max_total: null },
    });
  });

  it("rejects fractional, zero, and out-of-range limits", () => {
    expect(
      parseAgentSubagentPolicyDraft({ maxConcurrent: "1.5", maxTotal: "" }),
    ).toEqual({ ok: false, error: "max_concurrent" });
    expect(
      parseAgentSubagentPolicyDraft({ maxConcurrent: "0", maxTotal: "" }),
    ).toEqual({ ok: false, error: "max_concurrent" });
    expect(
      parseAgentSubagentPolicyDraft({ maxConcurrent: "", maxTotal: "51" }),
    ).toEqual({ ok: false, error: "max_total" });
    expect(MAX_AGENT_SUBAGENT_CONCURRENCY).toBe(64);
    expect(MAX_AGENT_SUBAGENTS_PER_RUN).toBe(50);
  });

  it("rejects browser number-input badInput instead of treating it as a clear", () => {
    expect(
      parseAgentSubagentPolicyDraft({
        maxConcurrent: "",
        maxTotal: "9",
        maxConcurrentBadInput: true,
      }),
    ).toEqual({ ok: false, error: "max_concurrent" });
  });
});

describe("thinkingEnabledToSelection", () => {
  it("maps null/undefined to inherit so an untouched save stays a no-op", () => {
    // Runtime default is thinking-on; a plain on/off switch seeded to false
    // would silently disable it. Inherit keeps the persisted null intact.
    expect(thinkingEnabledToSelection(null)).toBe(INHERIT_VALUE);
    expect(thinkingEnabledToSelection(undefined)).toBe(INHERIT_VALUE);
  });

  it("maps explicit booleans to on/off", () => {
    expect(thinkingEnabledToSelection(true)).toBe("on");
    expect(thinkingEnabledToSelection(false)).toBe("off");
  });
});

describe("Custom Agent subagent access", () => {
  it("round-trips all, none, and selected without collapsing null and []", () => {
    expect(allowedSubagentsToSelection(null)).toBe("all");
    expect(allowedSubagentsToSelection([])).toBe("none");
    expect(allowedSubagentsToSelection(["planner"])).toBe("selected");
    expect(selectionToAllowedSubagents("all", ["planner"])).toBeNull();
    expect(selectionToAllowedSubagents("none", ["planner"])).toEqual([]);
    expect(selectionToAllowedSubagents("selected", ["planner"])).toEqual([
      "planner",
    ]);
  });
});

describe("selectionToThinkingEnabled", () => {
  it("round-trips the tri-state back to the persisted value", () => {
    expect(selectionToThinkingEnabled(INHERIT_VALUE)).toBeNull();
    expect(selectionToThinkingEnabled("on")).toBe(true);
    expect(selectionToThinkingEnabled("off")).toBe(false);
  });
});

describe("resolveEffectiveModel", () => {
  const models: Model[] = [
    {
      id: "a",
      name: "a",
      model: "a",
      display_name: "A",
      supports_thinking: true,
    },
    { id: "b", name: "b", model: "b", display_name: "B" },
  ];

  it("resolves the default sentinel to the effective default (models[0])", () => {
    // An agent inheriting the global default must still surface the default
    // model's capabilities instead of hiding thinking/reasoning controls.
    expect(resolveEffectiveModel(models, DEFAULT_MODEL_VALUE)).toBe(models[0]);
  });

  it("resolves an explicit model by name", () => {
    expect(resolveEffectiveModel(models, "b")).toBe(models[1]);
  });

  it("returns undefined for an unknown model", () => {
    expect(resolveEffectiveModel(models, "missing")).toBeUndefined();
  });
});
