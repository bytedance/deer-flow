import { describe, expect, it } from "@rstest/core";

import type { Skill } from "@/core/skills";
import {
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
