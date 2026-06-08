type ClipboardItemLike = {
  types?: readonly string[];
  getType?: (type: string) => Promise<Blob>;
  items?: Record<string, Blob | string>;
};

function copyTextWithExecCommand(text: string): boolean {
  const document = globalThis.document;
  if (
    typeof document?.createElement !== "function" ||
    typeof document.body?.appendChild !== "function" ||
    typeof document.execCommand !== "function"
  ) {
    throw new Error("Clipboard DOM fallback not available");
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  textarea.style.left = "-9999px";

  let copied = false;
  let appended = false;
  try {
    document.body.appendChild(textarea);
    appended = true;
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    if (appended) {
      const parentNode = textarea.parentNode;
      if (typeof textarea.remove === "function") {
        textarea.remove();
      } else if (typeof parentNode?.removeChild === "function") {
        parentNode.removeChild(textarea);
      }
    }
  }

  return copied;
}

export async function writeTextToClipboard(text: string): Promise<boolean> {
  try {
    const clipboard = globalThis.navigator?.clipboard;
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return true;
    }

    return copyTextWithExecCommand(text);
  } catch {
    return false;
  }
}

function fallbackWriteText(text: string): Promise<void> {
  try {
    if (!copyTextWithExecCommand(text)) {
      return Promise.reject(new Error("Clipboard copy command failed"));
    }
  } catch (error) {
    return Promise.reject(
      error instanceof Error ? error : new Error(String(error)),
    );
  }
  return Promise.resolve();
}

function hasUsableClipboardItem(): boolean {
  return typeof globalThis.ClipboardItem === "function";
}

async function readPlainTextFromClipboardItem(
  item: ClipboardItemLike,
): Promise<string> {
  const plainText = item.items?.["text/plain"];
  if (typeof plainText === "string") {
    return plainText;
  }
  if (plainText instanceof Blob) {
    return await plainText.text();
  }

  if (item.types && !item.types.includes("text/plain")) {
    throw new Error("Clipboard item is missing text/plain data");
  }

  if (typeof item.getType !== "function") {
    throw new Error("Clipboard item cannot read text/plain data");
  }

  const blob = await item.getType("text/plain");
  if (blob instanceof Blob) {
    return await blob.text();
  }

  throw new Error("Clipboard item text/plain data is not a Blob");
}

function canDefineNavigatorClipboard(
  navigator: Navigator,
  descriptor: PropertyDescriptor | undefined,
): boolean {
  if (descriptor) {
    return descriptor.configurable === true;
  }
  return Object.isExtensible(navigator);
}

/**
 * Installs browser clipboard fallbacks for Streamdown copy controls by patching
 * missing navigator.clipboard methods and ClipboardItem when the host permits it.
 */
export function installClipboardFallback(): void {
  const navigator = globalThis.navigator;
  if (!navigator) {
    return;
  }

  const rawClipboard = navigator.clipboard;
  const clipboard =
    typeof rawClipboard === "object" && rawClipboard !== null
      ? (rawClipboard as Partial<Clipboard>)
      : undefined;
  const clipboardDescriptor = Object.getOwnPropertyDescriptor(
    navigator,
    "clipboard",
  );
  const hasWriteText = typeof clipboard?.writeText === "function";
  const hasWrite = typeof clipboard?.write === "function";
  const hasClipboardItem = hasUsableClipboardItem();

  if (hasWriteText && hasWrite && hasClipboardItem) {
    return;
  }

  const writeText = hasWriteText
    ? clipboard.writeText!.bind(clipboard)
    : fallbackWriteText;
  const write = hasWrite
    ? clipboard.write!.bind(clipboard)
    : (items: ClipboardItemLike[]) => {
        const firstItem = items[0];
        if (!firstItem) {
          return Promise.reject(new Error("Clipboard item not available"));
        }

        return readPlainTextFromClipboardItem(firstItem).then(writeText);
      };

  const fallbackClipboard = clipboard ?? {};

  try {
    const missingMethods: PropertyDescriptorMap = {};
    if (!hasWrite) {
      missingMethods.write = {
        configurable: true,
        value: write,
        writable: true,
      };
    }
    if (!hasWriteText) {
      missingMethods.writeText = {
        configurable: true,
        value: writeText,
        writable: true,
      };
    }

    Object.defineProperties(fallbackClipboard, missingMethods);

    if (
      !clipboard &&
      canDefineNavigatorClipboard(navigator, clipboardDescriptor)
    ) {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: fallbackClipboard,
      });
    }
  } catch {
    if (!canDefineNavigatorClipboard(navigator, clipboardDescriptor)) {
      // The ClipboardItem fallback below is independent from navigator.clipboard.
      if (hasClipboardItem) {
        return;
      }
    } else {
      const replacement = Object.create(clipboard ?? null);
      for (const methodName of ["read", "readText"] as const) {
        const method = clipboard?.[methodName];
        if (typeof method === "function") {
          Object.defineProperty(replacement, methodName, {
            configurable: true,
            value: method.bind(clipboard),
            writable: true,
          });
        }
      }
      Object.defineProperties(replacement, {
        write: {
          configurable: true,
          value: write,
          writable: true,
        },
        writeText: {
          configurable: true,
          value: writeText,
          writable: true,
        },
      });
      try {
        Object.defineProperty(navigator, "clipboard", {
          configurable: true,
          value: replacement,
        });
      } catch {
        // The ClipboardItem fallback below is independent from navigator.clipboard.
      }
    }
  }

  if (!hasClipboardItem) {
    class ClipboardItemFallback {
      items: Record<string, Blob | string>;
      types: string[];

      constructor(items: Record<string, Blob | string>) {
        this.items = items;
        this.types = Object.keys(items);
      }

      getType(type: string): Promise<Blob> {
        const value = this.items[type];
        if (value instanceof Blob) {
          return Promise.resolve(value);
        }
        if (typeof value === "string") {
          return Promise.resolve(new Blob([value], { type }));
        }
        return Promise.reject(
          new Error(`Clipboard item is missing ${type} data`),
        );
      }
    }

    try {
      Object.defineProperty(globalThis, "ClipboardItem", {
        configurable: true,
        value: ClipboardItemFallback,
      });
    } catch {
      return;
    }
  }
}
