import type { Skill } from "@/core/skills";

export const MAX_SKILL_SUGGESTIONS = 6;

export const SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN =
  /\[(?:主题|来源|topic|source)\]/i;

export type SlashSuggestion = {
  name: string;
  description: string;
  kind: "builtin" | "skill";
};

export type GoalCommand =
  | { kind: "status" }
  | { kind: "clear" }
  | { kind: "set"; objective: string };

export function findSuggestionTemplatePlaceholder(text: string) {
  const match = SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN.exec(text);
  if (!match) {
    return null;
  }

  return {
    start: match.index,
    end: match.index + match[0].length,
  };
}

export function getLeadingSlashSkillQuery(value: string): string | null {
  if (!value.startsWith("/")) {
    return null;
  }

  const query = value.slice(1);
  if (query.includes("/") || /\s/.test(query)) {
    return null;
  }

  return query;
}

export function getMatchingSkillSuggestions(
  skills: Skill[],
  query: string,
  builtinCommands: SlashSuggestion[],
): SlashSuggestion[] {
  const normalizedQuery = query.toLowerCase();

  const builtinMatches = builtinCommands.filter(({ name, description }) => {
    if (!normalizedQuery) {
      return true;
    }
    return (
      name.toLowerCase().includes(normalizedQuery) ||
      description.toLowerCase().includes(normalizedQuery)
    );
  });

  const skillMatches = skills
    .map((skill, index) => ({
      skill,
      index,
      name: skill.name.toLowerCase(),
    }))
    .filter(({ skill, name }) => {
      if (!skill.enabled) {
        return false;
      }
      return !normalizedQuery || name.includes(normalizedQuery);
    })
    .sort((a, b) => {
      const aStartsWith = a.name.startsWith(normalizedQuery);
      const bStartsWith = b.name.startsWith(normalizedQuery);
      if (aStartsWith !== bStartsWith) {
        return aStartsWith ? -1 : 1;
      }
      return a.index - b.index;
    })
    .slice(0, MAX_SKILL_SUGGESTIONS)
    .map(({ skill }) => ({
      name: skill.name,
      description: skill.description,
      kind: "skill" as const,
    }));

  return [...skillMatches, ...builtinMatches].slice(0, MAX_SKILL_SUGGESTIONS);
}

export function parseGoalCommand(value: string): GoalCommand | null {
  const trimmed = value.trim();
  const match = /^\/goal(?:\s+|$)/i.exec(trimmed);
  if (!match) {
    return null;
  }

  const args = trimmed.slice(match[0].length).trim();
  if (!args) {
    return { kind: "status" };
  }
  if (["clear", "reset", "off"].includes(args.toLowerCase())) {
    return { kind: "clear" };
  }
  return { kind: "set", objective: args };
}

export async function readGoalResponseError(
  response: Response,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Fall through to generic message.
  }
  return `HTTP ${response.status}`;
}
