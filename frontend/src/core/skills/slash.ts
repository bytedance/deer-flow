import type { Skill } from "./type";

/**
 * Composer control commands that own the leading slash. They must never be
 * shown as skill activations. These values plus {@link SLASH_SKILL_RE} mirror
 * the backend gate in `deerflow/skills/slash.py`; both sides are pinned to the
 * shared fixture at `contracts/slash_skill_contract.json` by contract tests
 * (`tests/unit/core/skills/slash-contract.test.ts` here,
 * `tests/test_slash_skill_contract.py` on the backend), so adding a reserved
 * command or changing the name grammar in only one language fails CI.
 */
export const RESERVED_SLASH_SKILL_NAMES = new Set([
  "bootstrap",
  "goal",
  "help",
  "memory",
  "models",
  "new",
  "status",
]);

export const SLASH_SKILL_RE = /^\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)/;

export type SlashSkillReference = {
  name: string;
  remainingText: string;
};

/**
 * Parse strict `/skill-name task` syntax, ignoring reserved control commands.
 * Mirrors the backend `parse_slash_skill_reference`; returns null when the text
 * is not a slash-skill activation.
 */
export function parseSlashSkillReference(
  text: string,
): SlashSkillReference | null {
  const match = SLASH_SKILL_RE.exec(text);
  if (!match) {
    return null;
  }
  const name = match[1];
  if (!name || RESERVED_SLASH_SKILL_NAMES.has(name)) {
    return null;
  }
  return {
    name,
    remainingText: text.slice(match[0].length).replace(/^\s+/, ""),
  };
}

/**
 * Resolve a slash-skill reference against the enabled skill catalog, matching
 * the backend `resolve_slash_skill` gate: only an installed + enabled skill
 * activates. Returns null when the text is not a slash command or the skill is
 * unknown/disabled, so callers fall back to plain-text rendering.
 */
export function resolveSlashSkillDisplay(
  text: string,
  skills: Skill[],
): SlashSkillReference | null {
  const reference = parseSlashSkillReference(text);
  if (!reference) {
    return null;
  }
  const enabled = skills.some(
    (skill) => skill.enabled && skill.name === reference.name,
  );
  return enabled ? reference : null;
}
