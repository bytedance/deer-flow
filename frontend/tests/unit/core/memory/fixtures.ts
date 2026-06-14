import type { UserMemory } from "@/core/memory/types";

/** Legacy export shape before user.cognitiveStyle existed (PR #3182). */
export function legacyMemoryWithoutCognitiveStyle(): Omit<
  UserMemory,
  "user"
> & {
  user: Omit<UserMemory["user"], "cognitiveStyle"> & {
    workContext: UserMemory["user"]["workContext"];
    personalContext: UserMemory["user"]["personalContext"];
    topOfMind: UserMemory["user"]["topOfMind"];
  };
} {
  return {
    version: "1.0",
    lastUpdated: "2026-01-01T00:00:00Z",
    user: {
      workContext: {
        summary: "Works on DeerFlow",
        updatedAt: "2026-01-01T00:00:00Z",
      },
      personalContext: { summary: "", updatedAt: "" },
      topOfMind: { summary: "Memory import compatibility", updatedAt: "" },
    },
    history: {
      recentMonths: { summary: "", updatedAt: "" },
      earlierContext: { summary: "", updatedAt: "" },
      longTermBackground: { summary: "", updatedAt: "" },
    },
    facts: [],
  };
}
