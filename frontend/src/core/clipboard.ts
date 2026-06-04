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
    return false;
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
      return Promise.reject(new Error("Clipboard API not available"));
    }
  } catch (error) {
    return Promise.reject(error);
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
  return (await blob?.text()) ?? "";
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

        const plainText = firstItem.items?.["text/plain"];
        if (typeof plainText === "string") {
          return writeText(plainText);
        }

        return readPlainTextFromClipboardItem(firstItem).then(writeText);
      };

  try {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        ...clipboard,
        write,
        writeText,
      },
    });
  } catch {
    return;
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
