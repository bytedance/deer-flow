import { describe, expect, it } from "@rstest/core";

import type { Skill } from "@/core/skills";
import {
  isActivatableSkillName,
  parseSlashSkillReference,
  resolveSlashSkillDisplay,
} from "@/core/skills/slash";

function makeSkill(name: string, enabled = true): Skill {
  return {
    name,
    description: `${name} description`,
    enabled,
  } as Skill;
}

describe("parseSlashSkillReference", () => {
  it("parses a leading /skill and captures the remaining text", () => {
    expect(parseSlashSkillReference("/data-analysis summarize this")).toEqual({
      name: "data-analysis",
      remainingText: "summarize this",
    });
  });

  it("parses a bare /skill with no task text", () => {
    expect(parseSlashSkillReference("/data-analysis")).toEqual({
      name: "data-analysis",
      remainingText: "",
    });
  });

  it("ignores reserved control commands", () => {
    expect(parseSlashSkillReference("/goal ship it")).toBeNull();
    expect(parseSlashSkillReference("/help")).toBeNull();
  });

  it("returns null when text is not a leading slash command", () => {
    expect(parseSlashSkillReference("hello /data-analysis")).toBeNull();
    expect(parseSlashSkillReference("/a/b")).toBeNull();
    expect(parseSlashSkillReference("plain text")).toBeNull();
  });
});

describe("isActivatableSkillName", () => {
  it("accepts exactly the lowercase-hyphen grammar of SLASH_SKILL_RE", () => {
    expect(isActivatableSkillName("data")).toBe(true);
    expect(isActivatableSkillName("data-analysis")).toBe(true);
    expect(isActivatableSkillName("a0-b1")).toBe(true);
    expect(isActivatableSkillName("DataTools")).toBe(false);
    expect(isActivatableSkillName("data tools")).toBe(false);
    expect(isActivatableSkillName("data_tools")).toBe(false);
    expect(isActivatableSkillName("data.tools")).toBe(false);
    expect(isActivatableSkillName("data--analysis")).toBe(false);
    expect(isActivatableSkillName("-data")).toBe(false);
    expect(isActivatableSkillName("data-")).toBe(false);
    expect(isActivatableSkillName("")).toBe(false);
  });

  it("agrees with the parser for every non-reserved name shape", () => {
    // The predicate has no grammar of its own to drift: it must classify a
    // name exactly as the production parser would receive it. If this ever
    // goes red, the predicate and SLASH_SKILL_RE disagree about what is
    // activatable — the reserved names are excluded only because the parser
    // additionally drops them, which is a separate shadowing layer the
    // catalogs apply on their own.
    const names = [
      "data",
      "data-analysis",
      "a0-b1",
      "DataTools",
      "data tools",
      "data_tools",
      "data.tools",
      "data--analysis",
      "-data",
      "data-",
      "",
    ];
    for (const name of names) {
      expect(isActivatableSkillName(name)).toBe(
        parseSlashSkillReference(`/${name} x`)?.name === name,
      );
    }
  });
});

describe("resolveSlashSkillDisplay", () => {
  const skills = [makeSkill("data-analysis"), makeSkill("frontend-design")];

  it("resolves when the referenced skill exists and is enabled", () => {
    expect(resolveSlashSkillDisplay("/data-analysis go", skills)).toEqual({
      name: "data-analysis",
      remainingText: "go",
    });
  });

  it("returns null for a slash command that is not an installed skill", () => {
    expect(resolveSlashSkillDisplay("/hello world", skills)).toBeNull();
    expect(resolveSlashSkillDisplay("/unknown-skill do it", skills)).toBeNull();
  });

  it("returns null when the skill exists but is disabled", () => {
    expect(
      resolveSlashSkillDisplay("/legacy-skill x", [
        makeSkill("legacy-skill", false),
      ]),
    ).toBeNull();
  });
});
