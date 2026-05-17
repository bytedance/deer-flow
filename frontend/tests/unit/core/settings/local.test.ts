import { expect, test } from "vitest";

import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

test("defaults token usage to header total plus per-turn breakdown", () => {
  expect(DEFAULT_LOCAL_SETTINGS.tokenUsage).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
});

test("defaults runtime memory context to disabled", () => {
  expect(DEFAULT_LOCAL_SETTINGS.context.memory_enabled).toBe(false);
});
