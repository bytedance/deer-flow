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

test("defaults collapsed thinking preview to disabled", () => {
  expect(DEFAULT_LOCAL_SETTINGS.appearance).toEqual({
    showCollapsedThinkingStep: false,
  });
});

test("merges collapsed thinking preview from persisted local settings", () => {
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
      appearance: {
        showCollapsedThinkingStep: true,
      },
    }),
  );

  expect(getLocalSettings().appearance.showCollapsedThinkingStep).toBe(true);
  expect(getLocalSettings().tokenUsage).toEqual(
    DEFAULT_LOCAL_SETTINGS.tokenUsage,
  );
});
