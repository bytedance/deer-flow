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

test("migrates legacy thinking_enabled / is_plan_mode to mode", () => {
  const store = new Map<string, string>();
  rs.stubGlobal("window", {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  });

  // thinking_enabled=true, no plan mode → mode = "thinking"
  store.set(
    "@deer-flow/local-settings",
    JSON.stringify({
      context: { thinking_enabled: true, is_plan_mode: false },
    }),
  );
  expect(getLocalSettings().context.mode).toBe("thinking");
  // Migration persisted the cleaned shape (no more legacy keys).
  const after1 = JSON.parse(store.get("@deer-flow/local-settings")!);
  expect(after1.context).not.toHaveProperty("thinking_enabled");
  expect(after1.context).not.toHaveProperty("is_plan_mode");
  expect(after1.context.mode).toBe("thinking");

  // is_plan_mode=true wins over thinking_enabled → mode = "pro"
  store.set(
    "@deer-flow/local-settings",
    JSON.stringify({
      context: { thinking_enabled: true, is_plan_mode: true },
    }),
  );
  expect(getLocalSettings().context.mode).toBe("pro");

  // Both legacy flags false → mode = "flash"
  store.set(
    "@deer-flow/local-settings",
    JSON.stringify({
      context: { thinking_enabled: false, is_plan_mode: false },
    }),
  );
  expect(getLocalSettings().context.mode).toBe("flash");

  // Modern entries with `mode` already set are not rewritten.
  store.set(
    "@deer-flow/local-settings",
    JSON.stringify({ context: { mode: "ultra", thinking_enabled: true } }),
  );
  expect(getLocalSettings().context.mode).toBe("ultra");
  const after4 = JSON.parse(store.get("@deer-flow/local-settings")!);
  expect(after4.context.thinking_enabled).toBe(true); // untouched
});
