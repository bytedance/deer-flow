import { describe, expect, it } from "@rstest/core";

import {
  abortGoalRequest,
  beginGoalRequest,
  createGoalRequestState,
  findSuggestionTemplatePlaceholder,
  finishGoalRequest,
  getInputSubmitAction,
  getLeadingSlashSkillQuery,
  getMatchingSkillSuggestions,
  isAbortError,
  isCurrentGoalRequest,
  parseCompactCommand,
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

describe("parseCompactCommand", () => {
  it("matches compact commands", () => {
    expect(parseCompactCommand("/compact")).toBe(true);
    expect(parseCompactCommand(" /context compact ")).toBe(true);
    expect(parseCompactCommand("/CONTEXT   COMPACT")).toBe(true);
  });

  it("rejects non-compact commands", () => {
    expect(parseCompactCommand("/compact now")).toBe(false);
    expect(parseCompactCommand("/context")).toBe(false);
    expect(parseCompactCommand("compact")).toBe(false);
  });
});

describe("getInputSubmitAction", () => {
  it("handles /goal commands before the streaming stop shortcut", () => {
    expect(
      getInputSubmitAction({
        text: "/goal ",
        fileCount: 0,
        status: "streaming",
      }),
    ).toEqual({ kind: "goal", command: { kind: "status" } });
  });

  it("handles /goal set commands before the streaming stop shortcut", () => {
    expect(
      getInputSubmitAction({
        text: "/goal finish the work",
        fileCount: 0,
        status: "streaming",
      }),
    ).toEqual({
      kind: "goal",
      command: { kind: "set", objective: "finish the work" },
    });
  });

  it("keeps ordinary streaming submits as stop", () => {
    expect(
      getInputSubmitAction({
        text: "hello",
        fileCount: 0,
        status: "streaming",
      }),
    ).toEqual({ kind: "stop" });
  });

  it("does not treat /goal text with attachments as a goal command", () => {
    expect(
      getInputSubmitAction({
        text: "/goal ",
        fileCount: 1,
        status: "ready",
      }),
    ).toEqual({ kind: "message" });
  });

  it("handles compact commands", () => {
    expect(
      getInputSubmitAction({
        text: "/compact",
        fileCount: 0,
        status: "ready",
      }),
    ).toEqual({ kind: "compact" });
    expect(
      getInputSubmitAction({
        text: "/context compact",
        fileCount: 0,
        status: "ready",
      }),
    ).toEqual({ kind: "compact" });
  });

  it("does not treat compact commands with attachments as compact", () => {
    expect(
      getInputSubmitAction({
        text: "/compact",
        fileCount: 1,
        status: "ready",
      }),
    ).toEqual({ kind: "message" });
  });

  it("ignores empty ready submits", () => {
    expect(
      getInputSubmitAction({
        text: "   ",
        fileCount: 0,
        status: "ready",
      }),
    ).toEqual({ kind: "empty" });
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

  it("excludes skills that collide with builtin command names", () => {
    const result = getMatchingSkillSuggestions(
      [makeSkill("goal"), makeSkill("goal-helper")],
      "goal",
      builtins,
    );

    expect(result.map((s) => `${s.kind}:${s.name}`)).toEqual([
      "skill:goal-helper",
      "builtin:goal",
    ]);
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

describe("goal request lifecycle", () => {
  it("aborts a pending goal request when the thread changes and blocks stale updates", () => {
    const state = createGoalRequestState();
    const first = beginGoalRequest(state, "thread-1");
    const updates: string[] = [];

    abortGoalRequest(state);
    const second = beginGoalRequest(state, "thread-2");

    if (isCurrentGoalRequest(state, first, "thread-1")) {
      updates.push("thread-1");
    }
    if (isCurrentGoalRequest(state, second, "thread-2")) {
      updates.push("thread-2");
    }

    expect(first.controller.signal.aborted).toBe(true);
    expect(second.controller.signal.aborted).toBe(false);
    expect(updates).toEqual(["thread-2"]);
  });

  it("does not let an older request finish a newer one", () => {
    const state = createGoalRequestState();
    const first = beginGoalRequest(state, "thread-1");
    const second = beginGoalRequest(state, "thread-1");

    finishGoalRequest(state, first);

    expect(isCurrentGoalRequest(state, second, "thread-1")).toBe(true);
  });

  it("recognizes abort-shaped errors", () => {
    expect(isAbortError(new DOMException("aborted", "AbortError"))).toBe(true);
    expect(
      isAbortError(Object.assign(new Error("aborted"), { name: "AbortError" })),
    ).toBe(true);
    expect(isAbortError(new Error("other"))).toBe(false);
  });

  it("supports compact request staleness guards with the same lifecycle", () => {
    const state = createGoalRequestState();
    const compact = beginGoalRequest(state, "thread-1");

    const replacement = beginGoalRequest(state, "thread-1");

    expect(compact.controller.signal.aborted).toBe(true);
    expect(isCurrentGoalRequest(state, compact, "thread-1")).toBe(false);
    expect(isCurrentGoalRequest(state, replacement, "thread-1")).toBe(true);

    finishGoalRequest(state, replacement);

    expect(isCurrentGoalRequest(state, replacement, "thread-1")).toBe(false);
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
