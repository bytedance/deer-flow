import { afterEach, describe, expect, rs, test } from "@rstest/core";

import {
  loadRememberLoginPreference,
  saveRememberLoginPreference,
} from "@/core/auth/remember-login";

function makeStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: rs.fn((key: string) => values.get(key) ?? null),
    setItem: rs.fn((key: string, value: string) => {
      values.set(key, value);
    }),
    removeItem: rs.fn((key: string) => {
      values.delete(key);
    }),
    values,
  };
}

describe("remember login helpers", () => {
  afterEach(() => {
    rs.unstubAllGlobals();
  });

  test("loads default keep-signed-in preference without a saved email", () => {
    const storage = makeStorage();
    rs.stubGlobal("localStorage", storage);

    expect(loadRememberLoginPreference()).toEqual({
      email: "",
      rememberMe: true,
    });
  });

  test("saves only email and preference when enabled", () => {
    const storage = makeStorage();
    rs.stubGlobal("localStorage", storage);

    saveRememberLoginPreference({
      email: "admin@example.com",
      rememberMe: true,
    });

    expect(storage.values.get("deerflow.auth.remember_login")).toBe("1");
    expect(storage.values.get("deerflow.auth.remembered_email")).toBe(
      "admin@example.com",
    );
    expect([...storage.values.values()]).not.toContain("password");
  });

  test("clears saved email when disabled", () => {
    const storage = makeStorage({
      "deerflow.auth.remember_login": "1",
      "deerflow.auth.remembered_email": "admin@example.com",
    });
    rs.stubGlobal("localStorage", storage);

    saveRememberLoginPreference({
      email: "admin@example.com",
      rememberMe: false,
    });

    expect(storage.values.get("deerflow.auth.remember_login")).toBe("0");
    expect(storage.values.has("deerflow.auth.remembered_email")).toBe(false);
  });

  test("falls back safely when localStorage is unavailable", () => {
    rs.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    });

    expect(loadRememberLoginPreference()).toEqual({
      email: "",
      rememberMe: true,
    });
    expect(() =>
      saveRememberLoginPreference({
        email: "admin@example.com",
        rememberMe: true,
      }),
    ).not.toThrow();
  });
});
