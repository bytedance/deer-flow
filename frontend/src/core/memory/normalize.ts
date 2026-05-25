import { normalizeMemoryPayload } from "./import-memory";
import type { UserMemory } from "./types";

/** Normalize API/import payloads (unknown → UserMemory). Throws if invalid. */
export function normalizeUserMemory(value: unknown): UserMemory {
  const normalized = normalizeMemoryPayload(value);
  if (!normalized) {
    throw new Error("Invalid memory payload");
  }
  return normalized;
}
