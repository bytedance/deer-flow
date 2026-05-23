import type { UserMemory } from "./types";

const emptySection = (): UserMemory["user"]["workContext"] => ({
  summary: "",
  updatedAt: "",
});

/** Ensure API/import payloads include cognitiveStyle (backward compatible). */
export function normalizeUserMemory(memory: UserMemory): UserMemory {
  return {
    ...memory,
    user: {
      ...memory.user,
      cognitiveStyle: memory.user.cognitiveStyle ?? emptySection(),
    },
  };
}
