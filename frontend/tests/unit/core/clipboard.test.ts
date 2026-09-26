import { afterEach, expect, test, rs } from "@rstest/core";

import {
  installClipboardFallback,
  writeTextToClipboard,
} from "@/core/clipboard";

const originalNavigator = globalThis.navigator;
const hadOriginalNavigator = "navigator" in globalThis;
const originalDocument = globalThis.document;
const hadOriginalDocument = "document" in globalThis;
const originalClipboardItemDescriptor = Object.getOwnPropertyDescriptor(
  globalThis,
  "ClipboardItem",
);

afterEach(() => {
  rs.restoreAllMocks();
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

  if (!originalClipboardItemDescriptor) {
    Reflect.deleteProperty(globalThis, "ClipboardItem");
  } else {
    Object.defineProperty(
      globalThis,
      "ClipboardItem",
      originalClipboardItemDescriptor,
    );
  }
});

test("writes text with the Clipboard API when available", async () => {
  const writeText = rs.fn().mockResolvedValue(undefined);
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
    remove: rs.fn(),
    select: rs.fn(),
    setAttribute: rs.fn(),
    style: {},
    value: "",
  };
  const appendChild = rs.fn();
  const execCommand = rs.fn().mockReturnValue(true);

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
      createElement: rs.fn().mockReturnValue(textarea),
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

test("falls back to parent removal when textarea.remove is unavailable", async () => {
  const parentNode = {
    removeChild: rs.fn(),
  };
  const textarea = {
    parentNode,
    select: rs.fn(),
    setAttribute: rs.fn(),
    style: {},
    value: "",
  };
  const execCommand = rs.fn().mockReturnValue(true);

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      body: {
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue(textarea),
      execCommand,
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(true);
  expect(parentNode.removeChild).toHaveBeenCalledWith(textarea);
});

test("does not fail cleanup when textarea removal APIs are unavailable", async () => {
  const textarea = {
    parentNode: {},
    select: rs.fn(),
    setAttribute: rs.fn(),
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
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue(textarea),
      execCommand: rs.fn().mockReturnValue(true),
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(true);
});

test("cleans up the textarea when selecting text fails", async () => {
  const textarea = {
    remove: rs.fn(),
    select: rs.fn(() => {
      throw new Error("selection failed");
    }),
    setAttribute: rs.fn(),
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
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue(textarea),
      execCommand: rs.fn(),
    },
  });

  await expect(writeTextToClipboard("hello")).resolves.toBe(false);
  expect(textarea.remove).toHaveBeenCalled();
});

test("returns false when execCommand fallback fails", async () => {
  const textarea = {
    remove: rs.fn(),
    select: rs.fn(),
    setAttribute: rs.fn(),
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
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue(textarea),
      execCommand: rs.fn().mockReturnValue(false),
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
        appendChild: rs.fn(),
      },
      execCommand: rs.fn(),
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
  const writeText = rs.fn().mockRejectedValue(new Error("denied"));
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
    remove: rs.fn(),
    select: rs.fn(),
    setAttribute: rs.fn(),
    style: {},
    value: "",
  };
  const appendChild = rs.fn();
  const execCommand = rs.fn().mockReturnValue(true);

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
      createElement: rs.fn().mockReturnValue(textarea),
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
  await expect(result).rejects.toThrow("Clipboard DOM fallback not available");
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
        appendChild: rs.fn(),
      },
      createElement: rs.fn(() => {
        throw new Error("dom unavailable");
      }),
      execCommand: rs.fn(),
    },
  });

  installClipboardFallback();

  const result = globalThis.navigator.clipboard.writeText("hello");
  expect(result).toBeInstanceOf(Promise);
  await expect(result).rejects.toThrow("dom unavailable");
});

test("installed writeText fallback distinguishes copy command failure", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      body: {
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue({
        remove: rs.fn(),
        select: rs.fn(),
        setAttribute: rs.fn(),
        style: {},
        value: "",
      }),
      execCommand: rs.fn().mockReturnValue(false),
    },
  });

  installClipboardFallback();

  await expect(
    globalThis.navigator.clipboard.writeText("hello"),
  ).rejects.toThrow("Clipboard copy command failed");
});

test("installs a write fallback for ClipboardItem text/plain payloads", async () => {
  const textarea = {
    remove: rs.fn(),
    select: rs.fn(),
    setAttribute: rs.fn(),
    style: {},
    value: "",
  };
  const execCommand = rs.fn().mockReturnValue(true);

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      body: {
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue(textarea),
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

test("installed write fallback rejects when ClipboardItem lacks text/plain", async () => {
  const execCommand = rs.fn().mockReturnValue(true);

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      body: {
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue({
        remove: rs.fn(),
        select: rs.fn(),
        setAttribute: rs.fn(),
        style: {},
        value: "",
      }),
      execCommand,
    },
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");

  installClipboardFallback();

  const item = new globalThis.ClipboardItem({
    "text/html": new Blob(["<table></table>"], { type: "text/html" }),
  });
  await expect(globalThis.navigator.clipboard.write([item])).rejects.toThrow(
    "Clipboard item is missing text/plain data",
  );
  expect(execCommand).not.toHaveBeenCalled();
});

test("installed write fallback rejects when getType cannot provide text/plain", async () => {
  const execCommand = rs.fn().mockReturnValue(true);

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      body: {
        appendChild: rs.fn(),
      },
      createElement: rs.fn().mockReturnValue({
        remove: rs.fn(),
        select: rs.fn(),
        setAttribute: rs.fn(),
        style: {},
        value: "",
      }),
      execCommand,
    },
  });

  installClipboardFallback();

  await expect(
    globalThis.navigator.clipboard.write([
      {
        getType: rs.fn().mockRejectedValue(new Error("missing")),
        types: ["text/plain"],
      } as unknown as ClipboardItem,
    ]),
  ).rejects.toThrow("missing");
  expect(execCommand).not.toHaveBeenCalled();
});

test("installed write fallback rejects before getType when item types exclude text/plain", async () => {
  const getType = rs.fn().mockResolvedValue(new Blob(["ignored"]));
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  installClipboardFallback();

  await expect(
    globalThis.navigator.clipboard.write([
      {
        getType,
        types: ["text/html"],
      } as unknown as ClipboardItem,
    ]),
  ).rejects.toThrow("Clipboard item is missing text/plain data");
  expect(getType).not.toHaveBeenCalled();
});

test("installed write fallback rejects when getType is missing", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  installClipboardFallback();

  await expect(
    globalThis.navigator.clipboard.write([
      {
        types: ["text/plain"],
      } as unknown as ClipboardItem,
    ]),
  ).rejects.toThrow("Clipboard item cannot read text/plain data");
});

test("installed write fallback rejects when getType returns a non-Blob", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  installClipboardFallback();

  await expect(
    globalThis.navigator.clipboard.write([
      {
        getType: rs.fn().mockResolvedValue("plain text"),
        types: ["text/plain"],
      } as unknown as ClipboardItem,
    ]),
  ).rejects.toThrow("Clipboard item text/plain data is not a Blob");
});

test("installed write fallback preserves existing clipboard prototype methods", async () => {
  const readText = rs.fn().mockResolvedValue("existing");
  const clipboard = Object.create({
    readText,
  });

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard,
    },
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");

  installClipboardFallback();

  expect(globalThis.navigator.clipboard).toBe(clipboard);
  await expect(globalThis.navigator.clipboard.readText()).resolves.toBe(
    "existing",
  );
  expect(readText).toHaveBeenCalled();
  await expect(
    globalThis.navigator.clipboard.writeText("hello"),
  ).rejects.toThrow("Clipboard DOM fallback not available");
});

test("installClipboardFallback does not replace existing clipboard methods when only ClipboardItem is missing", async () => {
  const write = rs.fn().mockResolvedValue(undefined);
  const writeText = rs.fn().mockResolvedValue(undefined);
  const clipboard = {
    write,
    writeText,
  };

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard,
    },
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");

  installClipboardFallback();

  expect(globalThis.navigator.clipboard).toBe(clipboard);
  expect(Reflect.get(globalThis.navigator.clipboard, "write")).toBe(write);
  expect(Reflect.get(globalThis.navigator.clipboard, "writeText")).toBe(
    writeText,
  );
  expect(typeof globalThis.ClipboardItem).toBe("function");
});

test("installClipboardFallback is idempotent for the same navigator", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");

  installClipboardFallback();
  const clipboard = globalThis.navigator.clipboard;
  const ClipboardItemFallback = globalThis.ClipboardItem;

  installClipboardFallback();

  expect(globalThis.navigator.clipboard).toBe(clipboard);
  expect(globalThis.ClipboardItem).toBe(ClipboardItemFallback);
});

test("installClipboardFallback can recover when the same navigator loses fallback globals", async () => {
  const navigator = {};
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: navigator,
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");

  installClipboardFallback();
  Reflect.deleteProperty(globalThis, "ClipboardItem");
  Reflect.deleteProperty(navigator, "clipboard");

  installClipboardFallback();

  expect(typeof globalThis.navigator.clipboard.writeText).toBe("function");
  expect(typeof globalThis.ClipboardItem).toBe("function");
});

test("installClipboardFallback defines writable fallback methods", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  installClipboardFallback();

  expect(
    Object.getOwnPropertyDescriptor(globalThis.navigator.clipboard, "write")
      ?.writable,
  ).toBe(true);
  expect(
    Object.getOwnPropertyDescriptor(globalThis.navigator.clipboard, "writeText")
      ?.writable,
  ).toBe(true);
});

test("installClipboardFallback skips missing clipboard on non-extensible navigator while installing ClipboardItem", async () => {
  const navigator = {};
  Object.preventExtensions(navigator);
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: navigator,
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");

  installClipboardFallback();

  expect("clipboard" in globalThis.navigator).toBe(false);
  expect(typeof globalThis.ClipboardItem).toBe("function");
});

test("installClipboardFallback handles non-object navigator.clipboard values", async () => {
  const navigator = {};
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: "locked",
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: navigator,
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  installClipboardFallback();

  expect(typeof globalThis.navigator.clipboard.writeText).toBe("function");
  await expect(
    globalThis.navigator.clipboard.writeText("hello"),
  ).rejects.toThrow("Clipboard DOM fallback not available");
});

test("installClipboardFallback does not throw when ClipboardItem cannot be defined", async () => {
  const originalDefineProperty = Object.defineProperty;
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {},
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });
  Reflect.deleteProperty(globalThis, "ClipboardItem");
  rs.spyOn(Object, "defineProperty").mockImplementation(
    (target, property, descriptor) => {
      if (target === globalThis && property === "ClipboardItem") {
        throw new Error("locked global");
      }
      return originalDefineProperty(target, property, descriptor);
    },
  );

  expect(() => installClipboardFallback()).not.toThrow();
  expect(typeof globalThis.navigator.clipboard.writeText).toBe("function");
  expect("ClipboardItem" in globalThis).toBe(false);
});

test("installs ClipboardItem fallback when the global property exists but is unusable", async () => {
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard: {
        write: rs.fn().mockResolvedValue(undefined),
        writeText: rs.fn().mockResolvedValue(undefined),
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
