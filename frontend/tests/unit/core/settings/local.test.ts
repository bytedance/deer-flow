import { afterEach, expect, rs, test } from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  getThreadModelName,
  saveLocalSettings,
  saveThreadModelName,
} from "@/core/settings/local";

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

function stubLocalStorage(payload: unknown) {
  const storage: Record<string, string | null> = {
    "deerflow.local-settings": JSON.stringify(payload),
  };
  rs.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => storage[key] ?? null,
      setItem: (key: string, value: string) => {
        storage[key] = value;
      },
      removeItem: (key: string) => {
        delete storage[key];
      },
    },
  });
}

test("migrates legacy top-level thinking_enabled/is_plan_mode into context.mode", () => {
  stubLocalStorage({ thinking_enabled: true, is_plan_mode: false });

  expect(getLocalSettings().context.mode).toBe("thinking");
  expect(
    "thinking_enabled" in
      (getLocalSettings().context as Record<string, unknown>)
  ).toBe(false);
  expect(
    "is_plan_mode" in (getLocalSettings().context as Record<string, unknown>)
  ).toBe(false);
});

test("plan mode wins over thinking mode during legacy migration", () => {
  stubLocalStorage({
    context: { thinking_enabled: true, is_plan_mode: true },
  });

  expect(getLocalSettings().context.mode).toBe("pro");
});

test("legacy all-false flags migrate to flash mode", () => {
  stubLocalStorage({ thinking_enabled: false, is_plan_mode: false });

  expect(getLocalSettings().context.mode).toBe("flash");
});

test("existing mode is preserved during legacy migration", () => {
  stubLocalStorage({
    context: {
      mode: "ultra",
      thinking_enabled: true,
      is_plan_mode: false,
    },
  });

  expect(getLocalSettings().context.mode).toBe("ultra");
});

test("settings without legacy flags are untouched", () => {
  stubLocalStorage({ projectsDisplayMode: "grouped" });

  expect(getLocalSettings()).toEqual({
    ...DEFAULT_LOCAL_SETTINGS,
    projectsDisplayMode: "grouped",
  });
});
