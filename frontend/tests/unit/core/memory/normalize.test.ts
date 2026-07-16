import { describe, expect, it } from "vitest";

import { normalizeUserMemory } from "@/core/memory/normalize";

import {
  legacyMemoryWithIncompleteFacts,
  legacyMemoryWithoutCognitiveStyle,
} from "./fixtures";

describe("normalizeUserMemory (API read path)", () => {
  it("fills cognitiveStyle when legacy payload omits it", () => {
    const result = normalizeUserMemory(legacyMemoryWithoutCognitiveStyle());

    expect(result.user.cognitiveStyle).toEqual({
      summary: "",
      updatedAt: "",
    });
    expect(result.user.workContext.summary).toBe("Works on DeerFlow");
  });

  it("throws when payload is not a valid memory object", () => {
    expect(() => normalizeUserMemory({})).toThrow("Invalid memory payload");
  });

  it("keeps the API read path available when one fact is unrecoverable", () => {
    const legacy = legacyMemoryWithIncompleteFacts();
    const result = normalizeUserMemory({
      ...legacy,
      facts: [...legacy.facts, { category: "context" }],
    });

    expect(result.facts).toHaveLength(1);
    expect(result.facts[0]).toMatchObject({
      content: "User prefers conclusions first.",
      category: "cognitive",
      confidence: 0,
      createdAt: "",
      source: "",
    });
  });
});
