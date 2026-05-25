import type { UserMemory } from "./types";

type ContextSection = UserMemory["user"]["workContext"];

const USER_SECTION_KEYS = [
  "workContext",
  "personalContext",
  "topOfMind",
  "cognitiveStyle",
] as const satisfies ReadonlyArray<keyof UserMemory["user"]>;

const HISTORY_SECTION_KEYS = [
  "recentMonths",
  "earlierContext",
  "longTermBackground",
] as const satisfies ReadonlyArray<keyof UserMemory["history"]>;

function emptySection(): ContextSection {
  return { summary: "", updatedAt: "" };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeContextSection(value: unknown): ContextSection {
  if (!isRecord(value)) {
    return emptySection();
  }

  return {
    summary: typeof value.summary === "string" ? value.summary : "",
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
  };
}

function isMemoryFact(value: unknown): value is UserMemory["facts"][number] {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.content === "string" &&
    typeof value.category === "string" &&
    typeof value.confidence === "number" &&
    Number.isFinite(value.confidence) &&
    typeof value.createdAt === "string" &&
    typeof value.source === "string"
  );
}

/**
 * Normalize and validate imported memory JSON (unknown → UserMemory | null).
 * Aligns with backend normalize_memory_data() for legacy exports.
 */
export function normalizeMemoryPayload(value: unknown): UserMemory | null {
  if (!isRecord(value)) {
    return null;
  }

  if (
    typeof value.version !== "string" ||
    typeof value.lastUpdated !== "string" ||
    !isRecord(value.user) ||
    !isRecord(value.history) ||
    !Array.isArray(value.facts)
  ) {
    return null;
  }

  if (!value.facts.every(isMemoryFact)) {
    return null;
  }

  const user = value.user;
  const history = value.history;

  return {
    version: value.version,
    lastUpdated: value.lastUpdated,
    user: {
      workContext: normalizeContextSection(user[USER_SECTION_KEYS[0]]),
      personalContext: normalizeContextSection(user[USER_SECTION_KEYS[1]]),
      topOfMind: normalizeContextSection(user[USER_SECTION_KEYS[2]]),
      cognitiveStyle: normalizeContextSection(user[USER_SECTION_KEYS[3]]),
    },
    history: {
      recentMonths: normalizeContextSection(history[HISTORY_SECTION_KEYS[0]]),
      earlierContext: normalizeContextSection(history[HISTORY_SECTION_KEYS[1]]),
      longTermBackground: normalizeContextSection(
        history[HISTORY_SECTION_KEYS[2]],
      ),
    },
    facts: value.facts,
  };
}
