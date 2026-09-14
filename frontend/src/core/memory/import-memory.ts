import type { UserMemory } from "./types";

type ContextSection = UserMemory["user"]["workContext"];
type MemoryFact = UserMemory["facts"][number];
type InvalidFactStrategy = "reject" | "drop";

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
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeContextSection(value: unknown): ContextSection {
  if (!isRecord(value)) {
    return emptySection();
  }

  return {
    ...value,
    summary: typeof value.summary === "string" ? value.summary : "",
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
  } as ContextSection;
}

function generateLegacyFactId(index: number): string {
  const randomUUID = globalThis.crypto?.randomUUID?.();
  return randomUUID
    ? `fact_${randomUUID.replaceAll("-", "").slice(0, 8)}`
    : `fact_legacy_${index}`;
}

function normalizeMemoryFact(value: unknown, index: number): MemoryFact | null {
  if (!isRecord(value)) {
    return null;
  }

  const content = typeof value.content === "string" ? value.content : "";
  if (!content.trim()) {
    return null;
  }

  const category =
    typeof value.category === "string" && value.category.trim()
      ? value.category.trim()
      : "context";
  const confidence =
    typeof value.confidence === "number" && Number.isFinite(value.confidence)
      ? Math.min(1, Math.max(0, value.confidence))
      : 0;

  const fact = {
    ...value,
    id:
      typeof value.id === "string" && value.id.trim()
        ? value.id.trim()
        : generateLegacyFactId(index),
    content,
    category,
    confidence,
    createdAt:
      typeof value.createdAt === "string" ? value.createdAt.trim() : "",
    source: typeof value.source === "string" ? value.source.trim() : "",
  } as MemoryFact & Record<string, unknown>;

  if (
    "sourceError" in fact &&
    fact.sourceError !== null &&
    typeof fact.sourceError !== "string"
  ) {
    delete fact.sourceError;
  }

  return fact;
}

/**
 * Normalize and validate memory JSON (unknown → UserMemory | null).
 *
 * Normalization is additive: only contract-owned fields are validated and
 * defaulted, while every unrecognized field (top-level, section, and per-fact)
 * passes through untouched. The frontend must never be narrower than the
 * Gateway contract — `MemoryResponse` declares fields such as the top-level
 * `revision`, and rebuilding from a whitelist here would silently drop them
 * from every response passing through `readMemoryResponse()`.
 *
 * The envelope (string `version`/`lastUpdated`, record `user`/`history`, array
 * `facts`) is strict on both call paths. Unrecoverable facts can either reject
 * a user-initiated import or be dropped on the background API read path.
 */
export function normalizeMemoryPayload(
  value: unknown,
  options: { invalidFactStrategy?: InvalidFactStrategy } = {},
): UserMemory | null {
  if (
    !isRecord(value) ||
    typeof value.version !== "string" ||
    typeof value.lastUpdated !== "string" ||
    !isRecord(value.user) ||
    !isRecord(value.history) ||
    !Array.isArray(value.facts)
  ) {
    return null;
  }

  const user = value.user;
  const history = value.history;
  const invalidFactStrategy = options.invalidFactStrategy ?? "reject";
  const facts: MemoryFact[] = [];

  for (const [index, factValue] of value.facts.entries()) {
    const fact = normalizeMemoryFact(factValue, index);
    if (!fact) {
      if (invalidFactStrategy === "reject") {
        return null;
      }
      continue;
    }
    facts.push(fact);
  }

  const normalizedUser = {
    ...user,
    ...Object.fromEntries(
      USER_SECTION_KEYS.map((key) => [key, normalizeContextSection(user[key])]),
    ),
  } as unknown as UserMemory["user"];
  const normalizedHistory = {
    ...history,
    ...Object.fromEntries(
      HISTORY_SECTION_KEYS.map((key) => [
        key,
        normalizeContextSection(history[key]),
      ]),
    ),
  } as unknown as UserMemory["history"];

  return {
    ...value,
    version: value.version,
    lastUpdated: value.lastUpdated,
    user: normalizedUser,
    history: normalizedHistory,
    facts,
  } as unknown as UserMemory;
}
