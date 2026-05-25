import { afterEach, expect, test, vi } from "vitest";

import { writeTextToClipboard } from "@/core/clipboard";

const originalNavigator = globalThis.navigator;
const hadOriginalNavigator = "navigator" in globalThis;

afterEach(() => {
  vi.restoreAllMocks();
  if (!hadOriginalNavigator) {
    Reflect.deleteProperty(globalThis, "navigator");
    return;
  }

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: originalNavigator,
  });
});

test("writes text with the Clipboard API when available", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard: {
        writeText,
      },
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(true);
  expect(writeText).toHaveBeenCalledWith("hello");
});

test("returns false when Clipboard API is unavailable", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(false);
});

test("returns false when navigator is unavailable", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: undefined,
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(false);
});

test("returns false when Clipboard API rejects", async () => {
  const writeText = vi.fn().mockRejectedValue(new Error("denied"));
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard: {
        writeText,
      },
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(false);
});
