import { describe, expect, it } from "@rstest/core";

import {
  DEFAULT_MODEL_VALUE,
  INHERIT_VALUE,
  MAX_AGENT_OUTPUT_TOKENS,
  parseAgentModelSettingsDraft,
  resolveEffectiveModel,
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
