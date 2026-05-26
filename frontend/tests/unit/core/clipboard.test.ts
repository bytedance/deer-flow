import { afterEach, expect, test, vi } from "vitest";

import { writeTextToClipboard } from "@/core/clipboard";

const originalNavigator = globalThis.navigator;
const hadOriginalNavigator = "navigator" in globalThis;
const originalDocument = globalThis.document;
const hadOriginalDocument = "document" in globalThis;

afterEach(() => {
  vi.restoreAllMocks();
  if (!hadOriginalNavigator) {
    Reflect.deleteProperty(globalThis, "navigator");
  } else {
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: originalNavigator,
    });
  }

  if (!hadOriginalDocument) {
    Reflect.deleteProperty(globalThis, "document");
  } else {
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: originalDocument,
    });
  }
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
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(false);
});

test("falls back to execCommand when Clipboard API is unavailable", async () => {
  const textarea = {
    remove: vi.fn(),
    select: vi.fn(),
    setAttribute: vi.fn(),
    style: {},
    value: "",
  };
  const appendChild = vi.fn();
  const execCommand = vi.fn().mockReturnValue(true);

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      body: {
        appendChild,
      },
      createElement: vi.fn().mockReturnValue(textarea),
      execCommand,
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(true);
  expect(textarea.value).toBe("hello");
  expect(appendChild).toHaveBeenCalledWith(textarea);
  expect(textarea.select).toHaveBeenCalled();
  expect(execCommand).toHaveBeenCalledWith("copy");
  expect(textarea.remove).toHaveBeenCalled();
});

test("returns false when execCommand fallback fails", async () => {
  const textarea = {
    remove: vi.fn(),
    select: vi.fn(),
    setAttribute: vi.fn(),
    style: {},
    value: "",
  };

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      body: {
        appendChild: vi.fn(),
      },
      createElement: vi.fn().mockReturnValue(textarea),
      execCommand: vi.fn().mockReturnValue(false),
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(false);
  expect(textarea.remove).toHaveBeenCalled();
});

test("returns false when navigator is unavailable", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(globalThis, "document", {
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
