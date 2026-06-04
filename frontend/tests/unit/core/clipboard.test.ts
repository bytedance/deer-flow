import { afterEach, expect, test, vi } from "vitest";

import {
  installClipboardFallback,
  writeTextToClipboard,
} from "@/core/clipboard";

const originalNavigator = globalThis.navigator;
const hadOriginalNavigator = "navigator" in globalThis;
const originalDocument = globalThis.document;
const hadOriginalDocument = "document" in globalThis;
const originalClipboardItem = globalThis.ClipboardItem;
const hadOriginalClipboardItem = "ClipboardItem" in globalThis;

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

  if (!hadOriginalClipboardItem) {
    Reflect.deleteProperty(globalThis, "ClipboardItem");
  } else {
    Object.defineProperty(globalThis, "ClipboardItem", {
      configurable: true,
      value: originalClipboardItem,
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

test("returns false when execCommand fallback cannot create an element", async () => {
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
      execCommand: vi.fn(),
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(false);
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

test("installs a writeText fallback when Clipboard API is unavailable", async () => {
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

  installClipboardFallback();

  await expect(globalThis.navigator.clipboard.writeText("hello")).resolves.toBe(
    undefined,
  );
  expect(textarea.value).toBe("hello");
  expect(appendChild).toHaveBeenCalledWith(textarea);
  expect(textarea.select).toHaveBeenCalled();
  expect(execCommand).toHaveBeenCalledWith("copy");
  expect(textarea.remove).toHaveBeenCalled();
});

test("installed writeText fallback rejects instead of throwing synchronously", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  installClipboardFallback();

  const result = globalThis.navigator.clipboard.writeText("hello");
  expect(result).toBeInstanceOf(Promise);
  await expect(result).rejects.toThrow("Clipboard API not available");
});

test("installed writeText fallback converts thrown DOM failures to rejections", async () => {
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
      createElement: vi.fn(() => {
        throw new Error("dom unavailable");
      }),
      execCommand: vi.fn(),
    },
  });

  installClipboardFallback();

  const result = globalThis.navigator.clipboard.writeText("hello");
  expect(result).toBeInstanceOf(Promise);
  await expect(result).rejects.toThrow("dom unavailable");
});

test("installs a write fallback for ClipboardItem text/plain payloads", async () => {
  const textarea = {
    remove: vi.fn(),
    select: vi.fn(),
    setAttribute: vi.fn(),
    style: {},
    value: "",
  };
  const execCommand = vi.fn().mockReturnValue(true);

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
      execCommand,
    },
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");

  installClipboardFallback();

  const item = new globalThis.ClipboardItem({
    "text/html": new Blob(["<table></table>"], { type: "text/html" }),
    "text/plain": "| A |\n| B |",
  });
  await expect(globalThis.navigator.clipboard.write([item])).resolves.toBe(
    undefined,
  );
  expect(textarea.value).toBe("| A |\n| B |");
  expect(execCommand).toHaveBeenCalledWith("copy");
});

test("installs ClipboardItem fallback when the global property exists but is unusable", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard: {
        write: vi.fn().mockResolvedValue(undefined),
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    },
  });
  Object.defineProperty(globalThis, "ClipboardItem", {
    configurable: true,
    value: undefined,
  });

  installClipboardFallback();

  expect(typeof globalThis.ClipboardItem).toBe("function");
});
