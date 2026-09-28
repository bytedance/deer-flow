import { describe, expect, it } from "@rstest/core";

import {
  getReasoningCapabilities,
  getReasoningEffortOptions,
  getResolvedMode,
  isThinkingRequired,
  reasoningEffortForMode,
  resolveReasoningEffort,
  supportsThinking,
} from "@/core/models/reasoning";
import type { Model } from "@/core/models/types";

function model(overrides: Partial<Model>): Model {
  return {
    id: "m",
    name: "m",
    model: "m",
    display_name: "M",
    ...overrides,
  };
}

const legacyThinking = model({
  supports_thinking: true,
  supports_reasoning_effort: true,
});

const legacyPlain = model({});

const glm = model({
  supports_thinking: true,
  supports_reasoning_effort: true,
  reasoning: {
    thinking: "required",
    effort: {
      values: ["low", "high", "max"],
      default: "max",
      aliases: { minimal: "low", medium: "high" },
    },
    history: "clear",
    source: "contract",
  },
});

const optionalNoEffort = model({
  reasoning: {
    thinking: "optional",
    effort: null,
    history: null,
    source: "contract",
  },
});

const restrictedNoDefault = model({
  reasoning: {
    thinking: "optional",
    effort: { values: ["low", "high"], default: null, aliases: {} },
    history: null,
    source: "contract",
  },
});

describe("getReasoningCapabilities", () => {
  it("falls back to the legacy booleans when the Gateway omits the contract", () => {
    expect(getReasoningCapabilities(legacyThinking)).toEqual({
      thinking: "optional",
      effort: {
        values: ["minimal", "low", "medium", "high"],
        default: null,
        aliases: {},
      },
      history: null,
      source: "legacy",
    });
    expect(getReasoningCapabilities(legacyPlain).thinking).toBe("unsupported");
    expect(getReasoningCapabilities(legacyPlain).effort).toBeNull();
  });

  it("treats a missing model as unsupported", () => {
    expect(getReasoningCapabilities(undefined).thinking).toBe("unsupported");
    expect(supportsThinking(undefined)).toBe(false);
    expect(getReasoningEffortOptions(null)).toEqual([]);
  });

  it("prefers the projected contract over the booleans", () => {
    expect(getReasoningCapabilities(glm).source).toBe("contract");
    expect(isThinkingRequired(glm)).toBe(true);
    expect(getReasoningEffortOptions(glm)).toEqual(["low", "high", "max"]);
  });
});

describe("resolveReasoningEffort", () => {
  it("keeps an unset value unset so the Gateway applies the contract default", () => {
    expect(resolveReasoningEffort(glm, undefined)).toBeUndefined();
  });

  it("keeps advertised legacy values and drops remembered contract-only values", () => {
    expect(resolveReasoningEffort(legacyThinking, "minimal")).toBe("minimal");
    expect(resolveReasoningEffort(legacyThinking, "xhigh")).toBeUndefined();
    expect(
      resolveReasoningEffort(
        legacyThinking,
        resolveReasoningEffort(glm, "max"),
      ),
    ).toBeUndefined();
    expect(resolveReasoningEffort(legacyPlain, "high")).toBeUndefined();
  });

  it("maps generic presets through the contract aliases", () => {
    expect(resolveReasoningEffort(glm, "minimal")).toBe("low");
    expect(resolveReasoningEffort(glm, "medium")).toBe("high");
    expect(resolveReasoningEffort(glm, "max")).toBe("max");
  });

  it("falls back to the contract default for unknown values", () => {
    expect(resolveReasoningEffort(glm, "xhigh")).toBe("max");
    expect(
      resolveReasoningEffort(restrictedNoDefault, "medium"),
    ).toBeUndefined();
  });

  it("drops any value for a model without effort control", () => {
    expect(resolveReasoningEffort(optionalNoEffort, "high")).toBeUndefined();
  });
});

describe("getResolvedMode", () => {
  it("clamps every mode to flash on a model without thinking", () => {
    expect(getResolvedMode("pro", legacyPlain)).toBe("flash");
    expect(getResolvedMode(undefined, legacyPlain)).toBe("flash");
  });

  it("keeps the requested mode on an optional-thinking model", () => {
    expect(getResolvedMode("flash", legacyThinking)).toBe("flash");
    expect(getResolvedMode("ultra", legacyThinking)).toBe("ultra");
    expect(getResolvedMode(undefined, legacyThinking)).toBe("pro");
  });

  it("never yields flash on a required-thinking model", () => {
    expect(getResolvedMode("flash", glm)).toBe("thinking");
    expect(getResolvedMode(undefined, glm)).toBe("pro");
    expect(getResolvedMode("ultra", glm)).toBe("ultra");
  });
});

describe("reasoningEffortForMode", () => {
  it("uses the generic presets for legacy models", () => {
    expect(reasoningEffortForMode("flash", legacyThinking)).toBe("minimal");
    expect(reasoningEffortForMode("thinking", legacyThinking)).toBe("low");
    expect(reasoningEffortForMode("pro", legacyThinking)).toBe("medium");
    expect(reasoningEffortForMode("ultra", legacyThinking)).toBe("high");
  });

  it("maps the presets onto a restricted contract", () => {
    expect(reasoningEffortForMode("thinking", glm)).toBe("low");
    expect(reasoningEffortForMode("pro", glm)).toBe("high");
    expect(reasoningEffortForMode("ultra", glm)).toBe("high");
  });
});
