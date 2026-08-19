import { afterEach, describe, expect, it } from "@rstest/core";

import {
  applySkinToDocument,
  isSkinId,
  prefersReducedMotion,
  readStoredSkin,
  SKIN_STORAGE_KEY,
  writeStoredSkin,
} from "@/core/skins";

const originalWindow = globalThis.window;
const hadWindow = "window" in globalThis;
const originalDocument = globalThis.document;
const hadDocument = "document" in globalThis;

afterEach(() => {
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

describe("workspace skins", () => {
  it("accepts classic and observatory", () => {
    expect(isSkinId("classic")).toBe(true);
    expect(isSkinId("observatory")).toBe(true);
    expect(isSkinId("glass")).toBe(false);
    expect(isSkinId(null)).toBe(false);
    expect(isSkinId("")).toBe(false);
  });

  it("falls back to classic when storage is missing or invalid", () => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          getItem: () => "glass",
        },
      },
    });
    expect(readStoredSkin()).toBe("classic");
  });

  it("returns classic when localStorage throws", () => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          getItem: () => {
            throw new Error("blocked");
          },
        },
      },
    });
    expect(readStoredSkin()).toBe("classic");
  });

  it("restores a stored observatory skin", () => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          getItem: (key: string) =>
            key === SKIN_STORAGE_KEY ? "observatory" : null,
        },
      },
    });
    expect(readStoredSkin()).toBe("observatory");
  });

  it("ignores write failures", () => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        localStorage: {
          setItem: () => {
            throw new Error("quota");
          },
        },
      },
    });
    expect(() => writeStoredSkin("observatory")).not.toThrow();
  });

  it("omits data-skin for classic and sets it for other skins", () => {
    const dataset: Record<string, string | undefined> = { skin: "observatory" };
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: {
        documentElement: { dataset },
      },
    });
    applySkinToDocument("classic");
    expect(dataset.skin).toBeUndefined();
    applySkinToDocument("observatory");
    expect(dataset.skin).toBe("observatory");
  });

  it("treats missing window as reduced motion", () => {
    Reflect.deleteProperty(globalThis, "window");
    expect(prefersReducedMotion()).toBe(true);
  });
});
