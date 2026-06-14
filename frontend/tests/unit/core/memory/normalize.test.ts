import { describe, expect, it } from "vitest";

import { normalizeUserMemory } from "@/core/memory/normalize";

import { legacyMemoryWithoutCognitiveStyle } from "./fixtures";

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
});
