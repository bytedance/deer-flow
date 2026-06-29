import { describe, expect, it } from "@rstest/core";

import {
  findSuggestionTemplatePlaceholder,
  getLeadingSlashSkillQuery,
  getMatchingSkillSuggestions,
  parseGoalCommand,
  readGoalResponseError,
  type SlashSuggestion,
} from "@/components/workspace/input-box-helpers";
import type { Skill } from "@/core/skills";

function makeSkill(name: string, enabled = true): Skill {
  return {
    name,
    description: `${name} description`,
    enabled,
  } as Skill;
}

// Builtin command names are bare (no leading slash); the composer renders them
// as `/${name}`. Mirror that shape here.
const builtins: SlashSuggestion[] = [
  {
    name: "goal",
    description: "Set, show, or clear an active goal",
    kind: "builtin",
  },
  { name: "new", description: "Start a new thread", kind: "builtin" },
];

describe("parseGoalCommand", () => {
  it("returns status for a bare /goal", () => {
    expect(parseGoalCommand("/goal")).toEqual({ kind: "status" });
    expect(parseGoalCommand("  /goal   ")).toEqual({ kind: "status" });
  });

  it("treats clear/reset/off as clear (case-insensitive)", () => {
    expect(parseGoalCommand("/goal clear")).toEqual({ kind: "clear" });
    expect(parseGoalCommand("/GOAL Reset")).toEqual({ kind: "clear" });
    expect(parseGoalCommand("/goal off")).toEqual({ kind: "clear" });
  });

  it("captures the objective for /goal <text>", () => {
    expect(parseGoalCommand("/goal ship the feature")).toEqual({
      kind: "set",
      objective: "ship the feature",
    });
  });

  it("returns null when the input is not a /goal command", () => {
    expect(parseGoalCommand("/goalkeeper do thing")).toBeNull();
    expect(parseGoalCommand("hello")).toBeNull();
    expect(parseGoalCommand("/new")).toBeNull();
  });
});

describe("getLeadingSlashSkillQuery", () => {
  it("returns the query for a leading slash token", () => {
    expect(getLeadingSlashSkillQuery("/rev")).toBe("rev");
    expect(getLeadingSlashSkillQuery("/")).toBe("");
  });

  it("returns null when there is no leading slash or the token is not bare", () => {
    expect(getLeadingSlashSkillQuery("rev")).toBeNull();
    expect(getLeadingSlashSkillQuery("/rev now")).toBeNull();
    expect(getLeadingSlashSkillQuery("/a/b")).toBeNull();
  });
});

describe("getMatchingSkillSuggestions", () => {
  it("excludes disabled skills and ranks prefix matches first", () => {
    const skills = [
      makeSkill("deep-research"),
      makeSkill("review"),
      makeSkill("reviewer-disabled", false),
    ];

    const result = getMatchingSkillSuggestions(skills, "rev", []);

    expect(result.map((s) => s.name)).toEqual(["review"]);
    expect(result.every((s) => s.kind === "skill")).toBe(true);
  });

  it("includes matching builtin commands after skills", () => {
    const result = getMatchingSkillSuggestions(
      [makeSkill("goal-helper")],
      "goal",
      builtins,
    );

    expect(result.map((s) => s.name)).toContain("goal-helper");
    expect(result.map((s) => s.name)).toContain("goal");
  });

  it("caps the number of suggestions", () => {
    const skills = Array.from({ length: 10 }, (_, i) =>
      makeSkill(`skill-${i}`),
    );
    const result = getMatchingSkillSuggestions(skills, "", []);
    expect(result.length).toBeLessThanOrEqual(6);
  });
});

describe("readGoalResponseError", () => {
  it("returns the detail string when present", async () => {
    const response = {
      status: 422,
      json: async () => ({ detail: "Goal objective must not be empty." }),
    } as unknown as Response;
    expect(await readGoalResponseError(response)).toBe(
      "Goal objective must not be empty.",
    );
  });

  it("falls back to the HTTP status when detail is missing or unparseable", async () => {
    const noDetail = {
      status: 500,
      json: async () => ({}),
    } as unknown as Response;
    expect(await readGoalResponseError(noDetail)).toBe("HTTP 500");

    const broken = {
      status: 503,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response;
    expect(await readGoalResponseError(broken)).toBe("HTTP 503");
  });
});

describe("findSuggestionTemplatePlaceholder", () => {
  it("locates a topic/source placeholder", () => {
    const found = findSuggestionTemplatePlaceholder("Research [topic] deeply");
    expect(found).not.toBeNull();
    expect(
      found && "Research [topic] deeply".slice(found.start, found.end),
    ).toBe("[topic]");
  });

  it("returns null when no placeholder is present", () => {
    expect(findSuggestionTemplatePlaceholder("no placeholder here")).toBeNull();
  });
});
