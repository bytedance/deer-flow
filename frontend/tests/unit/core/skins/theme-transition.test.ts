import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { applyObservatoryTheme } from "@/core/skins/theme-transition";

const originalWindow = globalThis.window;
const hadWindow = "window" in globalThis;
const originalDocument = globalThis.document;
const hadDocument = "document" in globalThis;

afterEach(() => {
  rs.useRealTimers();
  if (!hadWindow) {
    Reflect.deleteProperty(globalThis, "window");
  } else {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
  }
  if (!hadDocument) {
    Reflect.deleteProperty(globalThis, "document");
  } else {
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: originalDocument,
    });
  }
});

function installThemeEnv(skin?: string) {
  const classList = {
    added: new Set<string>(),
    add(name: string) {
      this.added.add(name);
    },
    remove(name: string) {
      this.added.delete(name);
    },
  };
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      documentElement: {
        dataset: skin ? { skin } : {},
        classList,
      },
    },
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      matchMedia: () => ({ matches: false }),
      setTimeout: (handler: () => void, timeout?: number) =>
        globalThis.setTimeout(handler, timeout),
      clearTimeout: (id?: number) => globalThis.clearTimeout(id),
      dispatchEvent: () => true,
    },
  });
}

describe("applyObservatoryTheme", () => {
  it("applies immediately when already on the same resolved mode", () => {
    const calls: string[] = [];
    installThemeEnv("observatory");
    applyObservatoryTheme("dark", "dark", (value) => {
      calls.push(value);
    });
    expect(calls).toEqual(["dark"]);
  });

  it("does not delay theme changes when observatory is not active", () => {
    const calls: string[] = [];
    installThemeEnv();
    applyObservatoryTheme("dark", "light", (value) => {
      calls.push(value);
    });
    expect(calls).toEqual(["dark"]);
  });

  it("cancels a pending delayed theme change", () => {
    rs.useFakeTimers();
    const calls: string[] = [];
    installThemeEnv("observatory");
    applyObservatoryTheme("dark", "light", (value) => {
      calls.push(value);
    });
    applyObservatoryTheme("light", "light", (value) => {
      calls.push(value);
    });
    rs.advanceTimersByTime(2000);
    expect(calls).toEqual(["light"]);
  });
});
