import { describe, expect, it } from "vitest";

import { normalizeMemoryPayload } from "@/core/memory/import-memory";

import { legacyMemoryWithoutCognitiveStyle } from "./fixtures";

/** Legacy strict guard (pre–normalizeMemoryPayload): required every section to exist. */
function isImportedMemoryStrict(value: unknown): boolean {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const record = value as Record<string, unknown>;
  if (
    typeof record.version !== "string" ||
    typeof record.lastUpdated !== "string" ||
    typeof record.user !== "object" ||
    record.user === null ||
    typeof record.history !== "object" ||
    record.history === null ||
    !Array.isArray(record.facts)
  ) {
    return false;
  }

  const user = record.user as Record<string, unknown>;
  const history = record.history as Record<string, unknown>;

  function isSection(section: unknown): boolean {
    if (typeof section !== "object" || section === null) {
      return false;
    }
    const s = section as Record<string, unknown>;
    return typeof s.summary === "string" && typeof s.updatedAt === "string";
  }

  return (
    isSection(user.workContext) &&
    isSection(user.personalContext) &&
    isSection(user.topOfMind) &&
    isSection(user.cognitiveStyle) &&
    isSection(history.recentMonths) &&
    isSection(history.earlierContext) &&
    isSection(history.longTermBackground)
  );
}

describe("legacy memory import compatibility (TDD)", () => {
  const legacy = legacyMemoryWithoutCognitiveStyle();

  it("legacy strict guard would reject exports missing cognitiveStyle", () => {
    expect(isImportedMemoryStrict(legacy)).toBe(false);
  });

  it("normalizeMemoryPayload accepts legacy export without cognitiveStyle", () => {
    const result = normalizeMemoryPayload(legacy);

    expect(result).not.toBeNull();
    expect(result!.user.cognitiveStyle).toEqual({
      summary: "",
      updatedAt: "",
    });
    expect(result!.user.workContext.summary).toBe("Works on DeerFlow");
  });

  it("normalizeMemoryPayload preserves existing cognitiveStyle summary", () => {
    const withStyle = {
      ...legacy,
      user: {
        ...legacy.user,
        cognitiveStyle: {
          summary: "Conclusions first, then details.",
          updatedAt: "2026-02-01T00:00:00Z",
        },
      },
    };

    const result = normalizeMemoryPayload(withStyle);

    expect(result).not.toBeNull();
    expect(result!.user.cognitiveStyle.summary).toBe(
      "Conclusions first, then details.",
    );
  });

  it("normalizeMemoryPayload returns null for non-object payloads", () => {
    expect(normalizeMemoryPayload(null)).toBeNull();
    expect(normalizeMemoryPayload("not-json")).toBeNull();
    expect(normalizeMemoryPayload({})).toBeNull();
  });

  it("normalizeMemoryPayload fills missing user sections like backend normalize", () => {
    const partial = {
      version: "1.0",
      lastUpdated: "",
      user: {
        workContext: { summary: "only work", updatedAt: "" },
      },
      history: {},
      facts: [],
    };

    const result = normalizeMemoryPayload(partial);

    expect(result).not.toBeNull();
    expect(result!.user.workContext.summary).toBe("only work");
    expect(result!.user.personalContext).toEqual({
      summary: "",
      updatedAt: "",
    });
    expect(result!.user.topOfMind).toEqual({ summary: "", updatedAt: "" });
    expect(result!.user.cognitiveStyle).toEqual({
      summary: "",
      updatedAt: "",
    });
    expect(result!.history.recentMonths).toEqual({
      summary: "",
      updatedAt: "",
    });
  });
});
