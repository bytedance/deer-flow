import { afterEach, expect, rs, test } from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  getLocalSettings,
  getThreadModelName,
  saveLocalSettings,
  saveThreadModelName,
} from "@/core/settings/local";
import { DEFAULT_NAV_LAYOUT } from "@/core/settings/nav-layout";

function createStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
    clear: () => {
      data.clear();
    },
  };
}

afterEach(() => {
  rs.unstubAllGlobals();
});

test("defaults token usage to header total plus per-turn breakdown", () => {
  expect(DEFAULT_LOCAL_SETTINGS.tokenUsage).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
});

test("falls back when localStorage access is blocked", () => {
  rs.stubGlobal("window", {
    get localStorage() {
      throw new DOMException("Blocked", "SecurityError");
    },
  });

  expect(getLocalSettings()).toEqual(DEFAULT_LOCAL_SETTINGS);
  expect(getThreadModelName("thread-1")).toBeUndefined();
  expect(() => saveLocalSettings(DEFAULT_LOCAL_SETTINGS)).not.toThrow();
  expect(() => saveThreadModelName("thread-1", "model-1")).not.toThrow();
});

test("defaults the nav layout to the shipped menu order", () => {
  expect(DEFAULT_LOCAL_SETTINGS.navLayout).toEqual(DEFAULT_NAV_LAYOUT);
});

test("persists a customized nav layout", () => {
  rs.stubGlobal("window", { localStorage: createStorage() });

  saveLocalSettings({
    ...DEFAULT_LOCAL_SETTINGS,
    navLayout: {
      version: 1,
      primary: ["search", "agents"],
      more: ["usage"],
    },
  });

  expect(getLocalSettings().navLayout).toEqual({
    version: 1,
    primary: ["search", "agents"],
    more: ["usage"],
  });
});

test("fills a missing nav layout from an older saved settings blob", () => {
  const storage = createStorage();
  storage.setItem(
    LOCAL_SETTINGS_KEY,
    JSON.stringify({ projectsDisplayMode: "grouped" }),
  );
  rs.stubGlobal("window", { localStorage: storage });

  const settings = getLocalSettings();

  expect(settings.projectsDisplayMode).toBe("grouped");
  expect(settings.navLayout).toEqual(DEFAULT_NAV_LAYOUT);
});

test("recovers from a corrupt stored nav layout", () => {
  const storage = createStorage();
  storage.setItem(
    LOCAL_SETTINGS_KEY,
    JSON.stringify({ navLayout: { version: 1, primary: "nope" } }),
  );
  rs.stubGlobal("window", { localStorage: storage });

  expect(getLocalSettings().navLayout).toEqual(DEFAULT_NAV_LAYOUT);
});
