import { afterEach, expect, test, vi } from "vitest";

import {
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  LOCAL_SETTINGS_KEY,
} from "@/core/settings/local";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("defaults token usage to header total plus per-turn breakdown", () => {
  expect(DEFAULT_LOCAL_SETTINGS.tokenUsage).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
});

test("defaults chat skill selection to all enabled skills", () => {
  expect(DEFAULT_LOCAL_SETTINGS.context.selected_skill_names).toBeUndefined();
});

test("merges selected skill names from persisted local settings", () => {
  const storage = new Map<string, string>();
  vi.stubGlobal("window", {});
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });

  localStorage.setItem(
    LOCAL_SETTINGS_KEY,
    JSON.stringify({
      context: {
        selected_skill_names: ["browser", "spreadsheet"],
      },
    }),
  );

  expect(getLocalSettings().context.selected_skill_names).toEqual([
    "browser",
    "spreadsheet",
  ]);
  expect(getLocalSettings().tokenUsage).toEqual(
    DEFAULT_LOCAL_SETTINGS.tokenUsage,
  );
});
