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
  document.body.appendChild(textarea);
  textarea.select();

  try {
    return document.execCommand("copy");
  } finally {
    textarea.remove();
  }
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

  const blob = await item.getType?.("text/plain");
  if (blob instanceof Blob) {
    return await blob.text();
  }

  throw new Error("Clipboard item type not available");
}

export function installClipboardFallback(): void {
  const navigator = globalThis.navigator;
  if (!navigator) {
    return;
  }

  const clipboard = navigator.clipboard as Partial<Clipboard> | undefined;
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
      };
    }
    if (!hasWriteText) {
      missingMethods.writeText = {
        configurable: true,
        value: writeText,
      };
    }

    Object.defineProperties(fallbackClipboard, missingMethods);

    if (!clipboard) {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: fallbackClipboard,
      });
    }
  } catch {
    const replacement = Object.create(clipboard ?? null);
    for (const methodName of ["read", "readText"] as const) {
      const method = clipboard?.[methodName];
      if (typeof method === "function") {
        Object.defineProperty(replacement, methodName, {
          configurable: true,
          value: method.bind(clipboard),
        });
      }
    }
    Object.defineProperties(replacement, {
      write: {
        configurable: true,
        value: write,
      },
      writeText: {
        configurable: true,
        value: writeText,
      },
    });
    try {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: replacement,
      });
    } catch {
      return;
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
        return Promise.reject(new Error("Clipboard item type not available"));
      }
    }

    Object.defineProperty(globalThis, "ClipboardItem", {
      configurable: true,
      value: ClipboardItemFallback,
    });
  }
}
